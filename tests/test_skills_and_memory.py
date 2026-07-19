from ai_cli import memory, skills as skills_mod


def _write_skill(base, subdir, name, description):
    skill_dir = base / subdir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nFull body for {name}.\n"
    )


def test_discovers_opencode_skills_global_and_project(tmp_path):
    bookmark = tmp_path / "bookmark"
    project = bookmark / "classic-car"
    project.mkdir(parents=True)

    _write_skill(bookmark, ".opencode/skills", "global-skill", "A global skill")
    _write_skill(project, ".opencode/skills", "car-skill", "Classic car specific skill")

    skills = skills_mod.discover_skills(bookmark, project)
    names = {s.name for s in skills}
    assert names == {"global-skill", "car-skill"}


def test_discovers_claude_fallback_dir(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    _write_skill(bookmark, ".claude/skills", "claude-compat-skill", "Interop skill")

    skills = skills_mod.discover_skills(bookmark, None)
    assert len(skills) == 1
    assert skills[0].name == "claude-compat-skill"


def test_project_skill_shadows_global_with_same_name(tmp_path):
    bookmark = tmp_path / "bookmark"
    project = bookmark / "proj"
    project.mkdir(parents=True)
    _write_skill(bookmark, ".opencode/skills", "shared-name", "global version")
    _write_skill(project, ".opencode/skills", "shared-name", "project version")

    skills = skills_mod.discover_skills(bookmark, project)
    assert len(skills) == 1
    assert skills[0].description == "project version"
    assert skills[0].scope == "project"


def test_system_prompt_block_only_has_name_and_description(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    _write_skill(bookmark, ".opencode/skills", "s1", "does a thing")
    skills = skills_mod.discover_skills(bookmark, None)
    block = skills_mod.skills_system_prompt_block(skills)
    assert "s1" in block
    assert "does a thing" in block
    assert "Full body" not in block  # body must not be eagerly disclosed


def test_read_skill_returns_full_body(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    _write_skill(bookmark, ".opencode/skills", "s1", "desc")
    skills = skills_mod.discover_skills(bookmark, None)
    body = skills_mod.read_skill(skills, "s1")
    assert "Full body for s1" in body


def test_memory_loads_global_and_project_agents_md(tmp_path):
    bookmark = tmp_path / "bookmark"
    project = bookmark / "proj"
    project.mkdir(parents=True)
    (bookmark / "AGENTS.md").write_text("global memory content")
    (project / "AGENTS.md").write_text("project memory content")

    block = memory.load_memory_block(project, bookmark, project)
    assert "global memory content" in block
    assert "project memory content" in block


def test_memory_falls_back_to_claude_md(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    (bookmark / "CLAUDE.md").write_text("claude fallback content")

    block = memory.load_memory_block(bookmark, bookmark, None)
    assert "claude fallback content" in block


def test_memory_tolerates_missing_files(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    block = memory.load_memory_block(bookmark, bookmark, None)
    assert block == ""
