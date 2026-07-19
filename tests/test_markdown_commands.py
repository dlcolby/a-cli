from pathlib import Path

from ai_cli.commands import markdown_command


def _write_command(base, name, frontmatter_lines, body):
    cmd_dir = base / ".opencode" / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    content = "---\n" + "\n".join(frontmatter_lines) + "\n---\n" + body
    (cmd_dir / f"{name}.md").write_text(content)


def test_discovers_project_and_global_commands(tmp_path):
    bookmark = tmp_path / "bookmark"
    project = bookmark / "proj"
    project.mkdir(parents=True)
    global_dir = tmp_path / "global_commands"
    global_dir.mkdir()

    _write_command(bookmark, "shared-cmd", ["description: shared"], "Shared body")
    _write_command(project, "proj-cmd", ["description: proj"], "Proj body $ARGUMENTS")

    commands = markdown_command.discover_commands(bookmark, project, global_dir)
    assert set(commands.keys()) == {"shared-cmd", "proj-cmd"}


def test_project_command_shadows_global(tmp_path):
    bookmark = tmp_path / "bookmark"
    project = bookmark / "proj"
    project.mkdir(parents=True)
    _write_command(bookmark, "dup", ["description: global version"], "global body")
    _write_command(project, "dup", ["description: project version"], "project body")

    commands = markdown_command.discover_commands(bookmark, project, None)
    assert commands["dup"].description == "project version"


def test_render_arguments_interpolation(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    _write_command(bookmark, "greet", ["description: greet"], "Hello $1, full args: $ARGUMENTS")
    commands = markdown_command.discover_commands(bookmark, None, None)
    rendered = markdown_command.render(commands["greet"], "Dave extra stuff", bookmark)
    assert rendered == "Hello Dave, full args: Dave extra stuff"


def test_render_file_interpolation(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    (bookmark / "notes.txt").write_text("note contents")
    _write_command(bookmark, "readnote", ["description: read"], "Contents: @notes.txt")
    commands = markdown_command.discover_commands(bookmark, None, None)
    rendered = markdown_command.render(commands["readnote"], "", bookmark)
    assert "note contents" in rendered


def test_render_file_interpolation_blocks_path_traversal(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("top secret")
    _write_command(bookmark, "leak", ["description: leak"], "Leaked: @../secret.txt")
    commands = markdown_command.discover_commands(bookmark, None, None)
    rendered = markdown_command.render(commands["leak"], "", bookmark)
    assert "top secret" not in rendered
    assert "blocked" in rendered


def test_shell_interpolation_disabled_by_default(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    _write_command(bookmark, "danger", ["description: danger"], "Result: !`echo pwned`")
    commands = markdown_command.discover_commands(bookmark, None, None)
    rendered = markdown_command.render(commands["danger"], "", bookmark)
    # The blocked placeholder may echo the literal command text for transparency,
    # but it must never be executed — assert it's wrapped in the disabled marker.
    assert "disabled" in rendered
    assert "[shell interpolation disabled: !`echo pwned`]" in rendered
