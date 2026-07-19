import subprocess

import pytest

from ai_cli import agent_tools


def test_read_file_roundtrip(tmp_path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    assert agent_tools.read_file(tmp_path, "a.txt") == "hello"


def test_read_file_missing_raises(tmp_path):
    with pytest.raises(agent_tools.ToolError):
        agent_tools.read_file(tmp_path, "missing.txt")


def test_read_file_truncates_large_files(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_tools, "MAX_FILE_READ_CHARS", 10)
    (tmp_path / "big.txt").write_text("x" * 100, encoding="utf-8")
    result = agent_tools.read_file(tmp_path, "big.txt")
    assert result.startswith("x" * 10)
    assert "truncated" in result


def test_write_file_creates_and_overwrites(tmp_path):
    agent_tools.write_file(tmp_path, "out.txt", "v1")
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "v1"
    agent_tools.write_file(tmp_path, "out.txt", "v2")
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "v2"


def test_write_file_creates_parent_dirs(tmp_path):
    agent_tools.write_file(tmp_path, "nested/dir/out.txt", "hi")
    assert (tmp_path / "nested" / "dir" / "out.txt").read_text(encoding="utf-8") == "hi"


def test_path_escape_is_refused_for_read(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(agent_tools.ToolError, match="escapes"):
        agent_tools.read_file(tmp_path, "../outside.txt")


def test_path_escape_is_refused_for_write(tmp_path):
    with pytest.raises(agent_tools.ToolError, match="escapes"):
        agent_tools.write_file(tmp_path, "../escape.txt", "pwned")
    assert not (tmp_path.parent / "escape.txt").exists()


def test_run_command_captures_stdout_and_exit_code(tmp_path):
    result = agent_tools.run_command(tmp_path, f"{_python_cmd()} -c \"print('hi')\"")
    assert "hi" in result
    assert "(exit 0)" in result


def test_run_command_runs_in_root(tmp_path):
    (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
    result = agent_tools.run_command(tmp_path, f"{_python_cmd()} -c \"import os; print(os.path.exists('marker.txt'))\"")
    assert "True" in result


def test_run_command_never_inherits_real_stdin(tmp_path, monkeypatch):
    # Regression: a device trace showed the terminal's own next read failing
    # with EBADF only after several run_command calls had already executed,
    # with no other change in between. a-shell can't use real fork() (spike
    # 4), so its subprocess.run/Popen implementation is necessarily some
    # non-standard shim -- explicitly isolating stdin removes any path for
    # it to touch the real terminal fd, regardless of the exact mechanism.
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(agent_tools.subprocess, "run", fake_run)
    agent_tools.run_command(tmp_path, "echo hi")
    assert captured["stdin"] == subprocess.DEVNULL


def test_run_command_timeout_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_tools, "COMMAND_TIMEOUT_SECONDS", 0.01)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="sleep", timeout=0.01)

    monkeypatch.setattr(agent_tools.subprocess, "run", fake_run)
    with pytest.raises(agent_tools.ToolError, match="timed out"):
        agent_tools.run_command(tmp_path, "sleep 5")


def test_execute_tool_dispatches(tmp_path):
    agent_tools.execute_tool(tmp_path, "write_file", {"path": "f.txt", "content": "hi"})
    assert agent_tools.execute_tool(tmp_path, "read_file", {"path": "f.txt"}) == "hi"


def test_execute_tool_unknown_raises(tmp_path):
    with pytest.raises(agent_tools.ToolError, match="Unknown tool"):
        agent_tools.execute_tool(tmp_path, "delete_everything", {})


def test_describe_tool_call_write_file():
    desc = agent_tools.describe_tool_call("write_file", {"path": "x.py", "content": "abcd"})
    assert "x.py" in desc and "4 chars" in desc


def test_describe_tool_call_run_command():
    desc = agent_tools.describe_tool_call("run_command", {"command": "pytest"})
    assert "pytest" in desc


def _python_cmd() -> str:
    import sys

    return f'"{sys.executable}"'
