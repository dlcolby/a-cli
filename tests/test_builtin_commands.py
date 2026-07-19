import pytest

from ai_cli.commands.builtin import cmd_model, cmd_mouse, cmd_session
from ai_cli.context import AppContext
from ai_cli.providers.anthropic_provider import AnthropicProvider


@pytest.fixture
def ctx(tmp_path):
    from ai_cli import config as config_mod

    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    provider = AnthropicProvider(api_key="fake")
    return AppContext(
        config=config_mod.Config(bookmark_root=str(bookmark)),
        cwd=bookmark,
        bookmark_root=bookmark,
        project_dir=None,
        provider_name="anthropic",
        provider=provider,
        model="sonnet",
    )


def test_model_refresh_clears_cache(ctx):
    ctx.model_cache["anthropic"] = ["stale"]
    result = cmd_model(ctx, "refresh")
    assert ctx.model_cache == {}
    assert "cleared" in result


def test_mouse_toggle_off_and_on(ctx):
    assert ctx.mouse_enabled is True
    result = cmd_mouse(ctx, "off")
    assert ctx.mouse_enabled is False
    assert "scrollback restored" in result

    result = cmd_mouse(ctx, "on")
    assert ctx.mouse_enabled is True
    assert "tap to select" in result


def test_mouse_invalid_arg_shows_current_state(ctx):
    result = cmd_mouse(ctx, "sideways")
    assert "Usage" in result
    assert "currently on" in result


def test_session_rename_updates_title_not_id(ctx):
    cmd_session(ctx, "new my-title")
    original_id = ctx.session.id
    result = cmd_session(ctx, "rename a better title")
    assert ctx.session.title == "a better title"
    assert ctx.session.id == original_id  # timestamp-based id must not change
    assert original_id in result


def test_session_rename_without_active_session(ctx):
    result = cmd_session(ctx, "rename whatever")
    assert "No active session" in result
