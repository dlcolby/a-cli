"""Long-term memory loader: AGENTS.md (falling back to CLAUDE.md), at both
global (bookmark root) and project (nearest ancestor under cwd) scope — same
convention OpenCode itself uses, so a file edited by either tool is picked up
by the other with zero translation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

MEMORY_FILENAMES = ("AGENTS.md", "CLAUDE.md")


def _find_memory_file(directory: Path) -> Optional[Path]:
    for name in MEMORY_FILENAMES:
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def load_memory_block(cwd: Path, bookmark_root: Path, project_dir: Optional[Path]) -> str:
    """Build the system-prompt memory block from global + project AGENTS.md/CLAUDE.md."""
    blocks = []

    global_file = _find_memory_file(bookmark_root)
    if global_file:
        blocks.append(f'<memory source="global" path="{global_file}">\n{global_file.read_text(encoding="utf-8")}\n</memory>')

    if project_dir is not None and project_dir.resolve() != bookmark_root.resolve():
        project_file = _find_memory_file(project_dir)
        if project_file:
            blocks.append(
                f'<memory source="project" path="{project_file}">\n{project_file.read_text(encoding="utf-8")}\n</memory>'
            )

    return "\n\n".join(blocks)


def append_note(directory: Path, note: str) -> Path:
    """Append a quick note to the AGENTS.md in `directory` (creating it if missing).
    Used by the /memory append built-in command."""
    path = directory / "AGENTS.md"
    directory.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Notes\n"
    if not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + f"\n- {note}\n", encoding="utf-8")
    return path
