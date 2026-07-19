"""Session store with project-vs-global scoping.

Global sessions live at <bookmark_root>/mobile_sessions/. Project sessions live
at <project>/mobile_sessions/, where <project> is the nearest ancestor of the
current working directory (up to and excluding bookmark_root) that looks like a
project — i.e. contains an AGENTS.md, a .opencode/ dir, or an existing
mobile_sessions/ dir. This mirrors OpenCode/Claude's own project-vs-global split
for skills/commands, applied to sessions: cd into the Classic Car project and
you only see Classic Car sessions (plus global ones); cd elsewhere and you don't.

Sessions are our own flat JSON files, deliberately independent of OpenCode's
internal SQLite session DB (which isn't a stable interchange format).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SESSIONS_DIRNAME = "mobile_sessions"
PROJECT_MARKERS = ("AGENTS.md", "CLAUDE.md", ".opencode", SESSIONS_DIRNAME)


@dataclass
class Session:
    id: str
    title: str
    provider: str
    model: str
    scope: str  # "project" | "global"
    path: str
    created_at: str
    updated_at: str
    messages: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "provider": self.provider,
            "model": self.model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": self.messages,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug[:max_len] or "session"


def find_project_dir(cwd: Path, bookmark_root: Path) -> Optional[Path]:
    """Walk up from cwd to (but not including a check above) bookmark_root looking
    for a directory with project markers. Returns None if cwd is at/above
    bookmark_root or no marker is found."""
    cwd = cwd.resolve()
    bookmark_root = bookmark_root.resolve()
    try:
        cwd.relative_to(bookmark_root)
    except ValueError:
        return None  # cwd isn't under the bookmark at all

    current = cwd
    while True:
        if current == bookmark_root:
            return None
        if any((current / marker).exists() for marker in PROJECT_MARKERS):
            return current
        if current.parent == current:
            return None
        current = current.parent


def global_sessions_dir(bookmark_root: Path) -> Path:
    return bookmark_root / SESSIONS_DIRNAME


def project_sessions_dir(cwd: Path, bookmark_root: Path) -> Optional[Path]:
    project = find_project_dir(cwd, bookmark_root)
    if project is None:
        return None
    return project / SESSIONS_DIRNAME


def list_sessions(cwd: Path, bookmark_root: Path) -> list[dict]:
    """Return lightweight metadata (no full transcripts) for in-scope sessions,
    sorted by updated_at descending."""
    results = []
    for scope, directory in (
        ("global", global_sessions_dir(bookmark_root)),
        ("project", project_sessions_dir(cwd, bookmark_root)),
    ):
        if directory is None or not directory.exists():
            continue
        for file in directory.glob("*.json"):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            results.append(
                {
                    "id": data.get("id"),
                    "title": data.get("title"),
                    "scope": scope,
                    "path": str(file),
                    "updated_at": data.get("updated_at", ""),
                }
            )
    results.sort(key=lambda s: s["updated_at"], reverse=True)
    return results


def create_session(
    cwd: Path, bookmark_root: Path, provider: str, model: str, title: str = "untitled", global_scope: bool = False
) -> Session:
    if global_scope:
        directory = global_sessions_dir(bookmark_root)
        scope = "global"
    else:
        directory = project_sessions_dir(cwd, bookmark_root)
        if directory is None:
            # No project markers found under cwd — fall back to global rather than error.
            directory = global_sessions_dir(bookmark_root)
            scope = "global"
        else:
            scope = "project"
    directory.mkdir(parents=True, exist_ok=True)
    session_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{_slugify(title)}-{uuid.uuid4().hex[:6]}"
    now = _now()
    session = Session(
        id=session_id,
        title=title,
        provider=provider,
        model=model,
        scope=scope,
        path=str(directory / f"{session_id}.json"),
        created_at=now,
        updated_at=now,
        messages=[],
    )
    save_session(session)
    return session


def load_session(path: str) -> Session:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Session(
        id=data["id"],
        title=data.get("title", data["id"]),
        provider=data.get("provider", ""),
        model=data.get("model", ""),
        scope=data.get("scope", "project"),
        path=path,
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        messages=data.get("messages", []),
    )


def save_session(session: Session) -> None:
    session.updated_at = _now()
    path = Path(session.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")
    os.replace(tmp_path, path)
    _write_markdown_mirror(session, path.with_suffix(".md"))


def _write_markdown_mirror(session: Session, md_path: Path) -> None:
    lines = [f"# {session.title}", "", f"_{session.provider}/{session.model} — updated {session.updated_at}_", ""]
    for msg in session.messages:
        lines.append(f"**{msg['role']}:**")
        lines.append("")
        lines.append(msg["content"])
        lines.append("")
    tmp_path = md_path.with_suffix(".md.tmp")
    tmp_path.write_text("\n".join(lines), encoding="utf-8")
    os.replace(tmp_path, md_path)


def delete_session(path: str) -> None:
    p = Path(path)
    p.unlink(missing_ok=True)
    p.with_suffix(".md").unlink(missing_ok=True)
