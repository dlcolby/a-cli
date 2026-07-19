"""Main REPL loop: foreground-only interactive chat, per the constraint that
a-shell suspends execution when backgrounded — there is no attempt to keep an
agentic loop running while the app isn't in front of the user.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path
from typing import Optional

try:
    import termios  # POSIX only — a-shell has it; the PC test suite may run on Windows, which doesn't
except ImportError:
    termios = None

from . import agent_tools, colors, config as config_mod, debug_log
from . import memory, naming, session as session_mod, skills as skills_mod, ui
from .commands import loader as command_loader
from .commands.markdown_command import discover_commands
from .context import AppContext
from .providers.base import Message, ToolCall, content_to_text, text_block, tool_result_block, tool_use_block
from .providers.registry import CHEAP_MODEL_BY_PROVIDER, create_provider
from .skills import READ_SKILL_TOOL

MAX_TOOL_ROUNDS = 12  # generous ceiling against a runaway agentic loop (read/write/run, not just read_skill)


def build_context(cwd: Path, provider_override: Optional[str], model_override: Optional[str]) -> AppContext:
    cfg = config_mod.Config.load()
    cfg.assert_secrets_isolated()

    if not cfg.bookmark_root:
        print("No shared workflow folder configured yet.")
        path = input("Enter the path to your shared (OneDrive-synced) workflow folder: ").strip()
        cfg.bookmark_root = path
        cfg.save()

    bookmark_root = Path(cfg.bookmark_root)
    bookmark_root.mkdir(parents=True, exist_ok=True)

    provider_name = provider_override or cfg.default_provider
    api_key = config_mod.get_api_key(provider_name)
    if not api_key:
        print(f"No API key found for '{provider_name}'.")
        api_key = input(f"Enter your {provider_name} API key: ").strip()
        secrets = config_mod.load_secrets()
        secrets[f"{provider_name}_api_key"] = api_key
        config_mod.save_secrets(secrets)

    provider = create_provider(provider_name, api_key)
    model = model_override or cfg.default_model_alias

    project_dir = session_mod.find_project_dir(cwd, bookmark_root)
    skills = skills_mod.discover_skills(bookmark_root, project_dir)
    global_commands_dir = Path(cfg.global_workflow_dir) / ".opencode" / "commands" if cfg.global_workflow_dir else None
    markdown_commands = discover_commands(bookmark_root, project_dir, global_commands_dir)

    return AppContext(
        config=cfg,
        cwd=cwd,
        bookmark_root=bookmark_root,
        project_dir=project_dir,
        provider_name=provider_name,
        provider=provider,
        model=model,
        skills=skills,
        markdown_commands=markdown_commands,
    )


AGENT_TOOLS_PROMPT_BLOCK = (
    "You have read_file/write_file/run_command tools scoped to the current project root. "
    "Paths are relative to that root. write_file and run_command will ask the user to confirm "
    "before they run — if the user declines, treat that as a hard stop for that action, not "
    "something to retry a different way."
)


def system_prompt(ctx: AppContext) -> str:
    parts = [memory.load_memory_block(ctx.cwd, ctx.bookmark_root, ctx.project_dir)]
    skills_block = skills_mod.skills_system_prompt_block(ctx.skills)
    if skills_block:
        parts.append(skills_block)
    parts.append(AGENT_TOOLS_PROMPT_BLOCK)
    return "\n\n".join(p for p in parts if p)


def _confirm(ctx: AppContext, prompt: str) -> bool:
    """y/N gate for write_file/run_command. History of failed approaches,
    device-tested on-device on 2026-07-19, in order:

    1. Bare input(). Hard-hung a-shell — no echo, force-quit required. Best
       explanation: the terminal was left in whatever raw-mode state
       prompt_toolkit's Application set up for the *previous* regular
       prompt() call; input()'s canonical-mode assumptions don't match that,
       so the read never completes the way it expects.
    2. Routing through ui.Repl_UI.confirm(), which called session.prompt()
       a second time on the same PromptSession mid-turn. This reproducibly
       crashed — OSError: [Errno 22] Invalid argument, from selectors.py's
       kqueue-based reader registration (loop.add_reader), at the exact same
       line every time, even after fixing an unrelated completer/mouse-hook
       bug in that path. Calling Application.run() a second time within the
       same process mid-turn is unreliable on a-shell's asyncio+kqueue
       combination, full stop — not a fixable detail, the wrong strategy.
    3. termios: OR in ICANON|ECHO onto whatever *live* (possibly raw-mode)
       lflags were currently set, then input(). Froze on-device — typed "y"
       echoed nothing, no crash, just stuck. Best explanation: POSIX termios
       reuses the same c_cc array slots for different purposes depending on
       ICANON (VMIN/VTIME in raw mode vs. VEOF/VEOL in canonical mode).
       prompt_toolkit likely has c_cc[VMIN] set to 0 for non-blocking raw
       reads; flipping ICANON back on without resetting c_cc reinterprets
       that same byte as VEOF, which can break canonical line-reading so
       input() never sees a completed line.

    Current approach: restore a full *pristine* snapshot (ctx.pristine_termios,
    captured once in main() before prompt_toolkit ever touches the terminal)
    rather than patching live/possibly-raw attributes — this guarantees
    internally consistent c_cc semantics for whichever mode it's in, since
    it's literally the terminal's own original state. Mouse tracking is
    disabled via a raw escape-code write first (pure output, no run loop, so
    it can't hit the kqueue issue from approach 2).

    Instrumented with debug_log calls throughout (see ai_cli/debug_log.py) —
    set AIC_DEBUG_LOG=<path> before running aic to get a timestamped trace of
    exactly how far this gets before any future freeze/crash.
    """
    debug_log.log(f"_confirm: start, prompt={prompt!r}")
    if ctx.repl_ui is not None:
        ctx.repl_ui.disable_mouse_now()
        debug_log.log("_confirm: mouse disabled")

    debug_log.log(f"_confirm: termios_available={termios is not None}, pristine_available={ctx.pristine_termios is not None}")
    fd = None
    live_attrs = None
    if termios is not None and ctx.pristine_termios is not None:
        try:
            fd = sys.stdin.fileno()
            live_attrs = termios.tcgetattr(fd)
            debug_log.log(f"_confirm: captured live termios lflag={live_attrs[3]}")
            termios.tcsetattr(fd, termios.TCSANOW, ctx.pristine_termios)
            debug_log.log(f"_confirm: restored pristine termios lflag={ctx.pristine_termios[3]}")
        except (termios.error, OSError, ValueError) as exc:
            debug_log.log(f"_confirm: termios restore failed: {exc!r}")
            live_attrs = None

    try:
        debug_log.log("_confirm: calling input()")
        reply = input(colors.wrap(f"{prompt} [y/N] ", colors.CONFIRM)).strip().lower()
        debug_log.log(f"_confirm: input() returned {reply!r}")
    finally:
        if live_attrs is not None:
            termios.tcsetattr(fd, termios.TCSANOW, live_attrs)
            debug_log.log("_confirm: re-applied live termios attrs")

    result = reply in ("y", "yes")
    debug_log.log(f"_confirm: returning {result}")
    return result


def _run_tool_call(ctx: AppContext, root: Path, tc: ToolCall) -> dict:
    """Execute a single tool call and return its tool_result block. Never
    raises — failures (including a declined confirmation) become an
    is_error tool_result so the model sees them and can react, rather than
    crashing the chat turn."""
    if tc.name == "read_skill":
        content = skills_mod.read_skill(ctx.skills, tc.input.get("name", ""))
        return tool_result_block(tc.id, content)

    if tc.name not in (t.name for t in agent_tools.AGENT_TOOLS):
        return tool_result_block(tc.id, f"Unknown tool '{tc.name}'", is_error=True)

    description = agent_tools.describe_tool_call(tc.name, tc.input)
    print(colors.wrap(f"[tool] {description}", colors.TOOL))
    if tc.name in agent_tools.CONFIRM_BEFORE_NAMES and not _confirm(ctx, f"Allow {description}?"):
        return tool_result_block(tc.id, "User declined to run this tool call.", is_error=True)

    try:
        content = agent_tools.execute_tool(root, tc.name, tc.input)
        return tool_result_block(tc.id, content)
    except agent_tools.ToolError as exc:
        return tool_result_block(tc.id, str(exc), is_error=True)


def send_turn(ctx: AppContext, user_text: str, override_model: Optional[str] = None) -> None:
    if ctx.session is None:
        ctx.session = session_mod.create_session(ctx.cwd, ctx.bookmark_root, ctx.provider_name, ctx.model)

    was_first_exchange = len(ctx.session.messages) == 0
    ctx.session.messages.append({"role": "user", "content": user_text})
    session_mod.save_session(ctx.session)  # save now — a crash later in this turn shouldn't lose the request
    model = override_model or ctx.model
    agent_root = ctx.project_dir or ctx.bookmark_root
    tools = list(agent_tools.AGENT_TOOLS)
    if ctx.skills:
        tools.append(READ_SKILL_TOOL)

    for _ in range(MAX_TOOL_ROUNDS):
        messages = [Message(role=m["role"], content=m["content"]) for m in ctx.session.messages]
        assistant_text = []
        tool_calls: list[ToolCall] = []

        print(colors.ASSISTANT, end="", flush=True)
        for event in ctx.provider.send(model, system_prompt(ctx), messages, tools=tools, stream=ctx.config.stream):
            if event.type == "text_delta":
                print(event.text, end="", flush=True)
                assistant_text.append(event.text)
            elif event.type == "tool_call":
                tool_calls.append(event.tool_call)
            elif event.type == "error":
                print(f"{colors.RESET}\n{colors.wrap(f'[error] {event.error}', colors.ERROR)}")
                return

        print(colors.RESET)  # newline after streamed text, closing the color span
        text = "".join(assistant_text)
        if tool_calls:
            blocks = ([text_block(text)] if text else []) + [
                tool_use_block(tc.id, tc.name, tc.input) for tc in tool_calls
            ]
            ctx.session.messages.append({"role": "assistant", "content": blocks})
        elif text:
            ctx.session.messages.append({"role": "assistant", "content": text})
        session_mod.save_session(ctx.session)  # persist each round — a crash mid-loop keeps prior rounds

        if not tool_calls:
            break

        result_blocks = [_run_tool_call(ctx, agent_root, tc) for tc in tool_calls]
        ctx.session.messages.append({"role": "user", "content": result_blocks})
        session_mod.save_session(ctx.session)  # persist tool results before the next network round
    else:
        print("\n[warning] tool-call loop hit its round limit; stopping]")

    if was_first_exchange and ctx.session.title == "untitled":
        try:
            cheap_model = CHEAP_MODEL_BY_PROVIDER.get(ctx.provider_name, model)
            assistant_reply = next(
                (content_to_text(m["content"]) for m in reversed(ctx.session.messages) if m["role"] == "assistant"),
                "",
            )
            title = naming.suggest_title(ctx.provider, cheap_model, user_text, assistant_reply)
            ctx.session.title = title
            print(colors.wrap(f'[session auto-named: "{title}" — /session rename to change it]', colors.SYSTEM))
        except Exception:
            pass  # naming is best-effort; never let it break the chat turn

    session_mod.save_session(ctx.session)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog="aic")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)

    ctx = build_context(Path.cwd(), args.provider, args.model)
    print(f"ai_cli — {ctx.provider_name}:{ctx.model}. Type /help for commands, /exit to quit.")

    # Snapshot the terminal's own attributes before prompt_toolkit ever runs
    # and puts it in raw mode — _confirm() restores this exact snapshot
    # rather than patching whatever (possibly raw) state is live at the time,
    # since that patching approach froze the terminal on-device. See
    # _confirm()'s docstring for the full history.
    if termios is not None:
        try:
            ctx.pristine_termios = termios.tcgetattr(sys.stdin.fileno())
        except (termios.error, OSError, ValueError):
            ctx.pristine_termios = None
    debug_log.log(f"main: pristine_termios captured={ctx.pristine_termios is not None}")

    repl_ui = ui.Repl_UI(ctx)
    ctx.repl_ui = repl_ui

    while not ctx.should_exit:
        try:
            line = repl_ui.prompt()
        except (EOFError, KeyboardInterrupt):
            line = "/exit"

        line = line.strip()
        if not line:
            continue

        try:
            if line.startswith("/"):
                result = command_loader.dispatch(ctx, line)
                if result.output is not None:
                    print(result.output)
                if result.chat_turn is not None:
                    send_turn(ctx, result.chat_turn, override_model=result.override_model)
            else:
                send_turn(ctx, line)
        except Exception:
            # A device crash previously left no trace at all — log the full
            # traceback before it propagates (or before the app dies without
            # one), so the log file has the last thing we know either way.
            debug_log.log(f"main loop: unhandled exception:\n{traceback.format_exc()}")
            raise


if __name__ == "__main__":
    main(sys.argv[1:])
