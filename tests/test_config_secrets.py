import os

import pytest

from ai_cli import config as config_mod


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
