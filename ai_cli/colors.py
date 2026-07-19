"""Minimal ANSI color helpers for the terminal-only parts of the UI (streamed
replies, transcript reprints, error text). These are raw escape codes printed
directly via plain print() — deliberately NOT routed through prompt_toolkit,
since this text is emitted outside any active PromptSession.prompt() call.
a-shell's terminal is confirmed to emulate xterm-256color, so basic ANSI SGR
codes are safe to assume support for.
"""

RESET = "\x1b[0m"
USER = "\x1b[36m"  # cyan
ASSISTANT = "\x1b[32m"  # green
SYSTEM = "\x1b[33m"  # yellow — auto-naming notices, warnings
ERROR = "\x1b[31m"  # red
TOOL = "\x1b[35m"  # magenta — "[tool] ..." call descriptions, distinct from assistant text
CONFIRM = "\x1b[1;33m"  # bold yellow — y/N prompts that need the user's attention/action


def wrap(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"
