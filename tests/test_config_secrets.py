import os

import pytest

from ai_cli import config as config_mod, repl


@pytest.fixture
def local_home(tmp_path, monkeypatch):
    home = tmp_path / "mobilecli-home"
    monkeypatch.setenv("MOBILECLI_HOME", str(home))
    return home


def test_env_var_takes_precedence_over_secrets_file(local_home, monkeypatch, tmp_path):
    config_mod.save_secrets({"anthropic_api_key": "from-file"})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert config_mod.get_api_key("anthropic") == "from-env"


def test_falls_back_to_secrets_file(local_home, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config_mod.save_secrets({"anthropic_api_key": "from-file"})
    assert config_mod.get_api_key("anthropic") == "from-file"


def test_missing_key_returns_none(local_home, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert config_mod.get_api_key("openai") is None


def test_assert_secrets_isolated_raises_when_bookmark_contains_secrets(local_home, tmp_path):
    cfg = config_mod.Config(bookmark_root=str(local_home.parent))
    with pytest.raises(RuntimeError):
        cfg.assert_secrets_isolated()


def test_assert_secrets_isolated_passes_for_unrelated_bookmark(local_home, tmp_path):
    bookmark = tmp_path / "onedrive-bookmark"
    bookmark.mkdir()
    cfg = config_mod.Config(bookmark_root=str(bookmark))
    cfg.assert_secrets_isolated()  # should not raise


def _set_home(monkeypatch, home_path) -> None:
    # Path.expanduser() consults $HOME on POSIX and %USERPROFILE% on
    # Windows -- set both so this test behaves the same regardless of which
    # platform it runs on (production is POSIX/a-shell; this dev box may be
    # Windows).
    monkeypatch.setenv("HOME", str(home_path))
    monkeypatch.setenv("USERPROFILE", str(home_path))


def test_assert_secrets_isolated_expands_tilde_before_comparing(local_home, monkeypatch):
    # Regression: Path() does NOT expand "~" on its own -- a device report
    # showed a "~"-prefixed bookmark_root being treated as a literal
    # relative path segment instead of the home directory, producing a
    # bogus nested project root and a real directory literally named "~"
    # inside the repo it happened to be launched from. If bookmark_root is
    # entered as "~/<something>" and never expanded, this guard would
    # compare against that literal (relative, cwd-dependent) path instead
    # of the real location -- silently failing to catch a genuine collision
    # with secrets. Rig HOME so "~/<local_home's name>" expands to exactly
    # where secrets.json lives, and confirm the guard actually catches it.
    _set_home(monkeypatch, local_home.parent)
    cfg = config_mod.Config(bookmark_root=f"~/{local_home.name}")
    with pytest.raises(RuntimeError):
        cfg.assert_secrets_isolated()


def test_build_context_expands_tilde_in_bookmark_root(local_home, monkeypatch, tmp_path):
    # Same bug, exercised through the actual first-run path: build_context()
    # is what a real "~"-typed answer to "Enter the path to your shared
    # workflow folder" flows through.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    _set_home(monkeypatch, fake_home)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    config_mod.Config(bookmark_root="~/workflow").save()

    ctx = repl.build_context(fake_home, None, None)

    assert ctx.bookmark_root == fake_home / "workflow"
    assert not (tmp_path / "~").exists()  # must never create a literal "~" dir as a side effect
