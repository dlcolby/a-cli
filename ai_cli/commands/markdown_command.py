"""OpenCode-style markdown slash commands: one .md file per command, YAML
frontmatter + a templated body. Discovered from project .opencode/commands/
and a global commands directory, matching OpenCode's own convention so a
command authored via OpenCode on PC works unmodified on mobile.

Supported interpolation (v1 scope): $ARGUMENTS, $1/$2/..., @file.
`!`shell`` interpolation is deliberately NOT supported by default — a synced
markdown file shouldn't silently gain shell-execution power. See
ALLOW_SHELL_INTERPOLATION.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

ALLOW_SHELL_INTERPOLATION = False  # deliberate v1 scope-cut; see module docstring

COMMAND_SUBDIRS = (".opencode/commands",)
SHELL_INTERP_RE = re.compile(r"!`([^`]*)`")
FILE_INTERP_RE = re.compile(r"@([^\s]+)")


@dataclass
class MarkdownCommand:
    name: str
    description: str
    agent: Optional[str]
    model: Optional[str]
    subtask: bool
    body: str
    path: Path


def _parse(path: Path) -> Optional[MarkdownCommand]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return MarkdownCommand(
        name=path.stem,
        description=frontmatter.get("description", ""),
        agent=frontmatter.get("agent"),
        model=frontmatter.get("model"),
        subtask=bool(frontmatter.get("subtask", False)),
        body=body,
        path=path,
    )


def discover_commands(bookmark_root: Path, project_dir: Optional[Path], global_commands_dir: Optional[Path]) -> dict:
    """Returns {name: MarkdownCommand}. Project commands shadow global ones,
    matching skills' precedence rule."""
    commands: dict[str, MarkdownCommand] = {}

    for subdir in COMMAND_SUBDIRS:
        base = bookmark_root / subdir
        if base.is_dir():
            for md_file in sorted(base.glob("*.md")):
                cmd = _parse(md_file)
                if cmd:
                    commands[cmd.name] = cmd

    if global_commands_dir and global_commands_dir.is_dir():
        for md_file in sorted(global_commands_dir.glob("*.md")):
            cmd = _parse(md_file)
            if cmd:
                commands[cmd.name] = cmd

    if project_dir is not None and project_dir.resolve() != bookmark_root.resolve():
        for subdir in COMMAND_SUBDIRS:
            base = project_dir / subdir
            if base.is_dir():
                for md_file in sorted(base.glob("*.md")):
                    cmd = _parse(md_file)
                    if cmd:
                        commands[cmd.name] = cmd

    return commands


def render(cmd: MarkdownCommand, argument_string: str, project_root: Path) -> str:
    """Render the command body with $ARGUMENTS/$1../@file interpolation.
    @file paths are resolved relative to project_root and must stay within it
    (path-traversal guard, since these files can come from a synced folder)."""
    args = argument_string.split()
    text = cmd.body.replace("$ARGUMENTS", argument_string)
    for i, arg in enumerate(args, start=1):
        text = text.replace(f"${i}", arg)

    def _replace_file(match: re.Match) -> str:
        rel_path = match.group(1)
        resolved = (project_root / rel_path).resolve()
        try:
            resolved.relative_to(project_root.resolve())
        except ValueError:
            return f"[blocked: @{rel_path} resolves outside project root]"
        if not resolved.exists():
            return f"[missing file: {rel_path}]"
        return resolved.read_text(encoding="utf-8")

    text = FILE_INTERP_RE.sub(_replace_file, text)

    if SHELL_INTERP_RE.search(text) and not ALLOW_SHELL_INTERPOLATION:
        text = SHELL_INTERP_RE.sub(
            lambda m: f"[shell interpolation disabled: !`{m.group(1)}`]", text
        )

    return text
