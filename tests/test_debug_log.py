from ai_cli import debug_log


def test_log_is_noop_when_env_var_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("AIC_DEBUG_LOG", raising=False)
    target = tmp_path / "should_not_exist.log"
    debug_log.log("hello")
    assert not target.exists()


def test_log_appends_timestamped_lines_when_enabled(monkeypatch, tmp_path):
    target = tmp_path / "debug.log"
    monkeypatch.setenv("AIC_DEBUG_LOG", str(target))
    debug_log.log("first")
    debug_log.log("second")
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("first")
    assert lines[1].endswith("second")


def test_log_never_raises_on_write_failure(monkeypatch, tmp_path):
    # A path under a nonexistent directory can't be opened for append --
    # logging must never be what crashes the app.
    monkeypatch.setenv("AIC_DEBUG_LOG", str(tmp_path / "missing_dir" / "debug.log"))
    debug_log.log("this should not raise")
