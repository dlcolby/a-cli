"""Skill discovery, matching OpenCode's own search order exactly so skills
authored via OpenCode/Claude Code on PC are picked up with zero translation.

Two-tier disclosure (same pattern OpenCode/Claude use): only name+description
go into the system prompt. The full SKILL.md body is fetched on demand via the
read_skill tool, once the model decides a skill looks relevant.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .providers.base import ToolDef

SKILL_SUBDIRS = (".opencode/skills", ".claude/skills", ".agents/skills")

READ_SKILL_TOOL = ToolDef(
    name="read_skill",
    description="Read the full instructions for a skill by name. Call this when a skill's "
    "description suggests it's relevant to the current task.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "The skill's name"}},
        "required": ["name"],
    },
)


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    scope: str  # "project" | "global"


def _parse_skill_md(path: Path) -> Optional[tuple[dict, str]]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return frontmatter, body


def _discover_in(root: Path, scope: str) -> list[Skill]:
    skills = []
    for subdir in SKILL_SUBDIRS:
        base = root / subdir
        if not base.is_dir():
            continue
        for skill_dir in sorted(base.iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            parsed = _parse_skill_md(skill_md)
            if parsed is None:
                continue
            frontmatter, _ = parsed
            name = frontmatter.get("name", skill_dir.name)
            description = frontmatter.get("description", "")
            skills.append(Skill(name=name, description=description, path=skill_md, scope=scope))
    return skills


def discover_skills(bookmark_root: Path, project_dir: Optional[Path]) -> list[Skill]:
    """Global skills come from bookmark_root; project skills from the nearest
    project directory (if any). Project skills with the same name shadow global
    ones, matching OpenCode's project-overrides-global precedence."""
    global_skills = {s.name: s for s in _discover_in(bookmark_root, "global")}
    if project_dir is not None and project_dir.resolve() != bookmark_root.resolve():
        for s in _discover_in(project_dir, "project"):
            global_skills[s.name] = s
    return sorted(global_skills.values(), key=lambda s: s.name)


def skills_system_prompt_block(skills: list[Skill]) -> str:
    if not skills:
        return ""
    lines = ["You have access to the following skills. Call read_skill(name) to load the full",
             "instructions for one when it looks relevant to the current task:", ""]
    for s in skills:
        lines.append(f"- {s.name}: {s.description}")
    return "\n".join(lines)


def read_skill(skills: list[Skill], name: str) -> str:
    for s in skills:
        if s.name == name:
            parsed = _parse_skill_md(s.path)
            return parsed[1] if parsed else ""
    return f"No skill named '{name}' found."
