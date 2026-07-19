"""Dispatches a slash-command line to either a built-in handler or a
markdown-defined command, and exposes the combined command list for the
UI layer's autocomplete."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import markdown_command
from .builtin import BUILTINS


@dataclass
class CommandResult:
    output: Optional[str] = None  # text to print directly
    chat_turn: Optional[str] = None  # text to send to the model instead
    override_model: Optional[str] = None


def all_command_names(ctx) -> list[str]:
    return list(BUILTINS.keys()) + list(ctx.markdown_commands.keys())


def dispatch(ctx, line: str) -> CommandResult:
    """line starts with '/'. Returns a CommandResult."""
    body = line[1:]
    name, _, rest = body.partition(" ")
    name = name.strip()
    rest = rest.strip()

    if name in BUILTINS:
        return CommandResult(output=BUILTINS[name](ctx, rest))

    if name in ctx.markdown_commands:
        cmd = ctx.markdown_commands[name]
        rendered = markdown_command.render(cmd, rest, ctx.project_dir or ctx.bookmark_root)
        return CommandResult(chat_turn=rendered, override_model=cmd.model)

    return CommandResult(output=f"Unknown command '/{name}'. Try /help.")
