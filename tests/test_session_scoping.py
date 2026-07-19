from pathlib import Path

from ai_cli import session as session_mod


def test_project_dir_found_via_agents_md(tmp_path):
    bookmark = tmp_path / "bookmark"
    project = bookmark / "classic-car"
    (project).mkdir(parents=True)
    (project / "AGENTS.md").write_text("car notes")
    nested = project / "subdir"
    nested.mkdir()

    found = session_mod.find_project_dir(nested, bookmark)
    assert found == project


def test_project_dir_found_via_git(tmp_path):
    # Regression: a git-managed project directory used to only be recognized
    # once a mobile_sessions/ dir already existed there -- but that dir is
    # gitignored, so a fresh clone lost the marker and project detection
    # silently fell back to bookmark_root, breaking agent-tool path
    # resolution (read_file etc. looked in the wrong directory).
    bookmark = tmp_path / "bookmark"
    project = bookmark / "some-repo"
    (project / ".git").mkdir(parents=True)
    nested = project / "subdir"
    nested.mkdir()

    found = session_mod.find_project_dir(nested, bookmark)
    assert found == project


def test_no_project_dir_when_no_markers(tmp_path):
    bookmark = tmp_path / "bookmark"
    loose = bookmark / "scratch"
    loose.mkdir(parents=True)
    assert session_mod.find_project_dir(loose, bookmark) is None


def test_cwd_outside_bookmark_returns_none(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert session_mod.find_project_dir(outside, bookmark) is None


def test_project_sessions_not_visible_outside_project(tmp_path):
    bookmark = tmp_path / "bookmark"
    project = bookmark / "classic-car"
    project.mkdir(parents=True)
    (project / "AGENTS.md").write_text("notes")

    other_dir = bookmark / "other-project"
    other_dir.mkdir()
    (other_dir / "AGENTS.md").write_text("notes")

    s = session_mod.create_session(project, bookmark, "anthropic", "sonnet", title="car session")
    assert s.scope == "project"

    from_project = {s["id"] for s in session_mod.list_sessions(project, bookmark)}
    from_other = {s["id"] for s in session_mod.list_sessions(other_dir, bookmark)}
    assert s.id in from_project
    assert s.id not in from_other


def test_global_session_visible_everywhere(tmp_path):
    bookmark = tmp_path / "bookmark"
    project = bookmark / "classic-car"
    project.mkdir(parents=True)
    (project / "AGENTS.md").write_text("notes")

    s = session_mod.create_session(project, bookmark, "anthropic", "sonnet", title="global note", global_scope=True)
    assert s.scope == "global"

    from_project = {sess["id"] for sess in session_mod.list_sessions(project, bookmark)}
    from_root = {sess["id"] for sess in session_mod.list_sessions(bookmark, bookmark)}
    assert s.id in from_project
    assert s.id in from_root


def test_format_session_label_combines_timestamp_and_title():
    label = session_mod.format_session_label("2026-07-19T05:38:46+00:00", "a great title")
    assert label == "2026-07-19 05:38 — a great title"


def test_format_session_label_falls_back_on_bad_timestamp():
    label = session_mod.format_session_label("not-a-timestamp", "a title")
    assert label == "not-a-timestamp — a title"


def test_format_transcript_empty(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    s = session_mod.create_session(bookmark, bookmark, "anthropic", "sonnet", global_scope=True)
    assert session_mod.format_transcript(s) == ""


def test_format_transcript_includes_all_messages(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    s = session_mod.create_session(bookmark, bookmark, "anthropic", "sonnet", global_scope=True)
    s.messages.append({"role": "user", "content": "hi"})
    s.messages.append({"role": "assistant", "content": "hello!"})
    text = session_mod.format_transcript(s)
    assert "[user] hi" in text
    assert "[assistant] hello!" in text


def test_save_and_load_roundtrip(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    s = session_mod.create_session(bookmark, bookmark, "anthropic", "sonnet", title="t", global_scope=True)
    s.messages.append({"role": "user", "content": "hello"})
    session_mod.save_session(s)

    loaded = session_mod.load_session(s.path)
    assert loaded.messages == [{"role": "user", "content": "hello"}]
    assert Path(s.path).with_suffix(".md").exists()
