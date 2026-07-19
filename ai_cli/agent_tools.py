"""Agentic file/command tools: read_file, write_file, run_command.

All three are scoped to a single root directory (the current project, or
bookmark_root if there's no project) — never the wider filesystem, mirroring
the secrets-isolation guard in config.py. write_file and run_command are
mutating/executing, so repl.py's tool loop gates them behind an interactive
confirmation before calling execute_tool().

run_command is built on subprocess only. See architecture.md's "Agentic
capability" section: os.fork() was confirmed on-device to trigger an
unrecoverable Fatal Python error that hangs the whole a-shell app, and
multiprocessing is ruled out transitively since it forks by default on
POSIX. Do not add either here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .providers.base import ToolDef

MAX_FILE_READ_CHARS = 200_000
MAX_COMMAND_OUTPUT_CHARS = 8_000
COMMAND_TIMEOUT_SECONDS = 60

READ_FILE_TOOL = ToolDef(
    name="read_file",
    description="Read a text file's contents, given a path relative to the project root.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path relative to the project root"}},
        "required": ["path"],
    },
)

WRITE_FILE_TOOL = ToolDef(
    name="write_file",
    description="Create or overwrite a text file, given a path relative to the project root and "
    "its full new content. The user is asked to confirm before this runs.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the project root"},
            "content": {"type": "string", "description": "The full new file content"},
        },
        "required": ["path", "content"],
    },
)

RUN_COMMAND_TOOL = ToolDef(
    name="run_command",
    description="Run a shell command in the project root and capture its output (stdout, stderr, "
    "exit code). The user is asked to confirm before this runs.",
    input_schema={
        "type": "object",
        "properties": {"command": {"type": "string", "description": "The shell command to run"}},
        "required": ["command"],
    },
)

AGENT_TOOLS = [READ_FILE_TOOL, WRITE_FILE_TOOL, RUN_COMMAND_TOOL]

# Tool names that mutate the filesystem or execute code — repl.py's tool loop
# requires an explicit user confirmation before running any of these.
CONFIRM_BEFORE_NAMES = {"write_file", "run_command"}


class ToolError(Exception):
    """Raised for any tool failure the model should see as a tool_result
    error (bad path, missing file, command timeout) — never let this escape
    as an unhandled exception and crash the chat turn."""


def _resolve_scoped_path(root: Path, rel_path: str) -> Path:
    root = root.resolve()
    candidate = (root / rel_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ToolError(f"Path '{rel_path}' escapes the project root — refusing.")
    return candidate


def read_file(root: Path, rel_path: str) -> str:
    path = _resolve_scoped_path(root, rel_path)
    if not path.is_file():
        raise ToolError(f"No such file: {rel_path}")
    data = path.read_text(encoding="utf-8", errors="replace")
    if len(data) > MAX_FILE_READ_CHARS:
        return data[:MAX_FILE_READ_CHARS] + f"\n...[truncated, file is {len(data)} chars]"
    return data


def write_file(root: Path, rel_path: str, content: str) -> str:
    path = _resolve_scoped_path(root, rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {rel_path}"


def run_command(root: Path, command: str) -> str:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            # Never let the executed command inherit the real terminal's
            # stdin (fd 0) — see architecture.md's "run_command inheriting
            # stdin" note: a device trace showed the terminal's own read
            # start failing with EBADF only after several run_command calls
            # had already executed, with no other change in between. a-shell
            # can't use real fork() (spike 4), so its subprocess.run/Popen
            # implementation is necessarily some non-standard shim rather
            # than fork+exec+dup2 — plausible it doesn't isolate stdin as
            # cleanly as a real POSIX subprocess would. DEVNULL removes any
            # path for that interaction regardless of the exact mechanism.
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"Command timed out after {COMMAND_TIMEOUT_SECONDS}s: {command}")
    output = f"$ {command}\n(exit {proc.returncode})\n{proc.stdout}"
    if proc.stderr:
        output += f"\n[stderr]\n{proc.stderr}"
    if len(output) > MAX_COMMAND_OUTPUT_CHARS:
        output = output[:MAX_COMMAND_OUTPUT_CHARS] + "\n...[truncated]"
    return output


def execute_tool(root: Path, name: str, tool_input: dict) -> str:
    """Dispatch by tool name. Raises ToolError on failure — callers should
    turn that into an is_error tool_result rather than letting it propagate."""
    if name == "read_file":
        return read_file(root, tool_input.get("path", ""))
    if name == "write_file":
        return write_file(root, tool_input.get("path", ""), tool_input.get("content", ""))
    if name == "run_command":
        return run_command(root, tool_input.get("command", ""))
    raise ToolError(f"Unknown tool '{name}'")


def describe_tool_call(name: str, tool_input: dict) -> str:
    """Human-readable one-liner shown in the confirmation prompt."""
    if name == "write_file":
        content_len = len(tool_input.get("content", ""))
        return f"write_file({tool_input.get('path')!r}, {content_len} chars)"
    if name == "run_command":
        return f"run_command({tool_input.get('command')!r})"
    return f"{name}({tool_input})"
