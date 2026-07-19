"""Main REPL loop: foreground-only interactive chat, per the constraint that
a-shell suspends execution when backgrounded — there is no attempt to keep an
agentic loop running while the app isn't in front of the user.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import traceback
from pathlib import Path
from typing import Optional

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
    "before they run, as their next chat message. If the user declines, treat that as a hard "
    "stop for that specific action — if they included a reason, treat it as guidance for a "
    "different approach, not something to retry unchanged."
)


def system_prompt(ctx: AppContext) -> str:
    parts = [memory.load_memory_block(ctx.cwd, ctx.bookmark_root, ctx.project_dir)]
    skills_block = skills_mod.skills_system_prompt_block(ctx.skills)
    if skills_block:
        parts.append(skills_block)
    parts.append(AGENT_TOOLS_PROMPT_BLOCK)
    return "\n\n".join(p for p in parts if p)


def _execute_tool_call(ctx: AppContext, root: Path, tc: ToolCall) -> dict:
    """Execute a single tool call (no confirmation gating here — callers
    decide whether/how to gate) and return its tool_result block. Never
    raises — failures become an is_error tool_result so the model sees them
    and can react, rather than crashing the chat turn."""
    if tc.name == "read_skill":
        content = skills_mod.read_skill(ctx.skills, tc.input.get("name", ""))
        return tool_result_block(tc.id, content)

    if tc.name not in (t.name for t in agent_tools.AGENT_TOOLS):
        return tool_result_block(tc.id, f"Unknown tool '{tc.name}'", is_error=True)

    try:
        content = agent_tools.execute_tool(root, tc.name, tc.input)
        return tool_result_block(tc.id, content)
    except agent_tools.ToolError as exc:
        return tool_result_block(tc.id, str(exc), is_error=True)


def _finish_turn(ctx: AppContext, model: str) -> None:
    """Auto-name the session on its first completed exchange (best-effort —
    naming failures never break the chat turn), then save. Uses the actual
    first stored message rather than a value threaded through every resume
    step, so it works the same whether the turn finished in one round or
    was paused and resumed across several confirmations."""
    if ctx.session.title == "untitled" and ctx.session.messages and ctx.session.messages[0]["role"] == "user":
        try:
            cheap_model = CHEAP_MODEL_BY_PROVIDER.get(ctx.provider_name, model)
            first_user_text = content_to_text(ctx.session.messages[0]["content"])
            assistant_reply = next(
                (content_to_text(m["content"]) for m in reversed(ctx.session.messages) if m["role"] == "assistant"),
                "",
            )
            title = naming.suggest_title(ctx.provider, cheap_model, first_user_text, assistant_reply)
            ctx.session.title = title
            print(colors.wrap(f'[session auto-named: "{title}" — /session rename to change it]', colors.SYSTEM))
        except Exception:
            pass  # naming is best-effort; never let it break the chat turn

    session_mod.save_session(ctx.session)


def _advance_tool_calls(
    ctx: AppContext,
    model: str,
    agent_root: Path,
    tools: list,
    rounds_left: int,
    remaining: list[ToolCall],
    result_blocks: list[dict],
) -> None:
    """Work through this round's tool calls in order, executing each
    immediately unless it needs confirmation — in which case this pauses
    here (storing everything needed to resume on ctx.pending_confirmation)
    instead of blocking for input. See ctx.pending_confirmation's docstring
    and resume_pending_confirmation() below for why: a synchronous nested
    read/prompt mid-turn was tried five different ways (bare input(), a
    nested prompt_toolkit Application, termios variations) and every one
    either hung or crashed on-device. Reusing the main loop's own already-
    reliable prompt() for the next line, instead of trying to grab a read
    out-of-band mid-turn, sidesteps that whole class of bug by construction."""
    remaining = list(remaining)
    while remaining:
        tc = remaining[0]
        if tc.name != "read_skill":
            description = agent_tools.describe_tool_call(tc.name, tc.input)
            print(colors.wrap(f"[tool] {description}", colors.TOOL))
            if tc.name in agent_tools.CONFIRM_BEFORE_NAMES:
                ctx.pending_confirmation = {
                    "model": model,
                    "agent_root": agent_root,
                    "tools": tools,
                    "rounds_left": rounds_left,
                    "remaining_tool_calls": remaining,
                    "result_blocks": result_blocks,
                }
                print(
                    colors.wrap(
                        f'Allow {description}? Reply "y"/"yes" as your next message to proceed — '
                        "anything else declines it (include a reason and it'll be passed back to the model).",
                        colors.CONFIRM,
                    )
                )
                return
        result_blocks = result_blocks + [_execute_tool_call(ctx, agent_root, tc)]
        remaining = remaining[1:]

    ctx.session.messages.append({"role": "user", "content": result_blocks})
    session_mod.save_session(ctx.session)  # persist tool results before the next network round
    _run_round(ctx, model, agent_root, tools, rounds_left)


def _run_round(ctx: AppContext, model: str, agent_root: Path, tools: list, rounds_left: int) -> None:
    if rounds_left <= 0:
        print("\n[warning] tool-call loop hit its round limit; stopping]")
        _finish_turn(ctx, model)
        return
    rounds_left -= 1

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
        _finish_turn(ctx, model)
        return

    _advance_tool_calls(ctx, model, agent_root, tools, rounds_left, tool_calls, [])


def send_turn(ctx: AppContext, user_text: str, override_model: Optional[str] = None) -> None:
    if ctx.session is None:
        ctx.session = session_mod.create_session(ctx.cwd, ctx.bookmark_root, ctx.provider_name, ctx.model)

    ctx.session.messages.append({"role": "user", "content": user_text})
    session_mod.save_session(ctx.session)  # save now — a crash later in this turn shouldn't lose the request
    model = override_model or ctx.model
    agent_root = ctx.project_dir or ctx.bookmark_root
    tools = list(agent_tools.AGENT_TOOLS)
    if ctx.skills:
        tools.append(READ_SKILL_TOOL)

    _run_round(ctx, model, agent_root, tools, MAX_TOOL_ROUNDS)


def resume_pending_confirmation(ctx: AppContext, reply_text: str) -> None:
    """Handle the user's next typed line as the answer to a pending
    write_file/run_command confirmation (see ctx.pending_confirmation).
    "y"/"yes" (case-insensitive) proceeds; anything else declines — a bare
    "n"/"no"/empty reply declines with no extra detail, anything longer is
    passed back to the model as the user's stated reason, so declining can
    double as redirection ("no, use -maxdepth 2 instead") rather than a
    dead end."""
    pending = ctx.pending_confirmation
    ctx.pending_confirmation = None
    remaining = pending["remaining_tool_calls"]
    tc = remaining[0]
    reply = reply_text.strip()

    if reply.lower() in ("y", "yes"):
        result_block = _execute_tool_call(ctx, pending["agent_root"], tc)
    elif reply.lower() in ("", "n", "no"):
        result_block = tool_result_block(tc.id, "User declined to run this tool call.", is_error=True)
    else:
        result_block = tool_result_block(
            tc.id, f"User declined to run this tool call and said: {reply}", is_error=True
        )

    result_blocks = pending["result_blocks"] + [result_block]
    _advance_tool_calls(
        ctx, pending["model"], pending["agent_root"], pending["tools"], pending["rounds_left"], remaining[1:], result_blocks
    )


async def _main_async(argv: Optional[list[str]]) -> None:
    parser = argparse.ArgumentParser(prog="aic")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)

    ctx = build_context(Path.cwd(), args.provider, args.model)
    print(f"ai_cli — {ctx.provider_name}:{ctx.model}. Type /help for commands, /exit to quit.")

    repl_ui = ui.Repl_UI(ctx)
    ctx.repl_ui = repl_ui

    while not ctx.should_exit:
        try:
            line = await repl_ui.prompt()
        except (EOFError, KeyboardInterrupt):
            line = "/exit"
        except Exception:
            # A device crash here previously produced a raw traceback with no
            # debug_log entry at all, since this call sat outside the
            # exception-logging block below — log it here too now.
            debug_log.log(f"main loop: unhandled exception in prompt():\n{traceback.format_exc()}")
            raise

        line = line.strip()
        if not line:
            continue

        try:
            if line.startswith("/"):
                result = command_loader.dispatch(ctx, line)
                if result.output is not None:
                    print(result.output)
                if result.chat_turn is not None:
                    if ctx.pending_confirmation is not None:
                        print(
                            colors.wrap(
                                "[warning] a tool confirmation is still pending — answer that first "
                                "(y/yes or a reason to decline) before running a command that sends a new message]",
                                colors.SYSTEM,
                            )
                        )
                    else:
                        send_turn(ctx, result.chat_turn, override_model=result.override_model)
            elif ctx.pending_confirmation is not None:
                resume_pending_confirmation(ctx, line)
            else:
                send_turn(ctx, line)
        except Exception:
            # A device crash previously left no trace at all — log the full
            # traceback before it propagates (or before the app dies without
            # one), so the log file has the last thing we know either way.
            debug_log.log(f"main loop: unhandled exception:\n{traceback.format_exc()}")
            raise


def main(argv: Optional[list[str]] = None) -> None:
    # A single asyncio.run() for the REPL's entire lifetime, not one per
    # prompt() call — see Repl_UI.prompt()'s docstring: repeatedly creating
    # and tearing down an event loop (and its kqueue selector) once per turn
    # is the leading theory for a device crash that surfaced several turns
    # into a session, on an otherwise perfectly ordinary prompt() call.
    asyncio.run(_main_async(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
