"""Main REPL loop: foreground-only interactive chat, per the constraint that
a-shell suspends execution when backgrounded — there is no attempt to keep an
agentic loop running while the app isn't in front of the user.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from . import config as config_mod
from . import memory, session as session_mod, skills as skills_mod, ui
from .commands import loader as command_loader
from .commands.markdown_command import discover_commands
from .context import AppContext
from .providers.base import Message, ToolCall
from .providers.registry import create_provider
from .skills import READ_SKILL_TOOL

MAX_TOOL_ROUNDS = 4  # generous ceiling against a runaway read_skill loop


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


def system_prompt(ctx: AppContext) -> str:
    parts = [memory.load_memory_block(ctx.cwd, ctx.bookmark_root, ctx.project_dir)]
    skills_block = skills_mod.skills_system_prompt_block(ctx.skills)
    if skills_block:
        parts.append(skills_block)
    return "\n\n".join(p for p in parts if p)


def send_turn(ctx: AppContext, user_text: str, override_model: Optional[str] = None) -> None:
    if ctx.session is None:
        ctx.session = session_mod.create_session(ctx.cwd, ctx.bookmark_root, ctx.provider_name, ctx.model)

    ctx.session.messages.append({"role": "user", "content": user_text})
    model = override_model or ctx.model
    tools = [READ_SKILL_TOOL] if ctx.skills else None

    for _ in range(MAX_TOOL_ROUNDS):
        messages = [Message(role=m["role"], content=m["content"]) for m in ctx.session.messages]
        assistant_text = []
        tool_calls: list[ToolCall] = []

        for event in ctx.provider.send(model, system_prompt(ctx), messages, tools=tools, stream=ctx.config.stream):
            if event.type == "text_delta":
                print(event.text, end="", flush=True)
                assistant_text.append(event.text)
            elif event.type == "tool_call":
                tool_calls.append(event.tool_call)
            elif event.type == "error":
                print(f"\n[error] {event.error}")
                return

        print()  # newline after streamed text
        if assistant_text:
            ctx.session.messages.append({"role": "assistant", "content": "".join(assistant_text)})

        if not tool_calls:
            break

        # Simplified tool exchange: represented as synthetic text turns rather
        # than provider-native structured tool_use/tool_result blocks (see
        # providers/base.py Message docstring). Good enough for a single
        # read-only tool; would need real structured content for richer tools.
        for tc in tool_calls:
            if tc.name == "read_skill":
                result = skills_mod.read_skill(ctx.skills, tc.input.get("name", ""))
            else:
                result = f"Unknown tool '{tc.name}'"
            ctx.session.messages.append(
                {"role": "user", "content": f"[Tool result for {tc.name}({tc.input})]\n{result}"}
            )
    else:
        print("\n[warning] tool-call loop hit its round limit; stopping]")

    session_mod.save_session(ctx.session)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog="aic")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)

    ctx = build_context(Path.cwd(), args.provider, args.model)
    print(f"ai_cli — {ctx.provider_name}:{ctx.model}. Type /help for commands, /exit to quit.")

    repl_ui = ui.Repl_UI(ctx)

    while not ctx.should_exit:
        try:
            line = repl_ui.prompt()
        except (EOFError, KeyboardInterrupt):
            line = "/exit"

        line = line.strip()
        if not line:
            continue

        if line.startswith("/"):
            result = command_loader.dispatch(ctx, line)
            if result.output is not None:
                print(result.output)
            if result.chat_turn is not None:
                send_turn(ctx, result.chat_turn, override_model=result.override_model)
        else:
            send_turn(ctx, line)


if __name__ == "__main__":
    main(sys.argv[1:])
