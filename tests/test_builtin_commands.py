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


def test_mouse_mode_defaults_to_auto(ctx):
    assert ctx.mouse_mode == "auto"


def test_mouse_mode_switches_between_all_three(ctx):
    result = cmd_mouse(ctx, "off")
    assert ctx.mouse_mode == "off"
    assert "scrollback works everywhere" in result

    result = cmd_mouse(ctx, "on")
    assert ctx.mouse_mode == "on"
    assert "tap to select" in result

    result = cmd_mouse(ctx, "auto")
    assert ctx.mouse_mode == "auto"
    assert "automatically" in result


def test_mouse_invalid_arg_shows_current_state(ctx):
    result = cmd_mouse(ctx, "sideways")
    assert "Usage" in result
    assert "currently auto" in result


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


def test_session_switch_prints_transcript(ctx):
    cmd_session(ctx, "new my-session")
    ctx.session.messages.append({"role": "user", "content": "hello there"})
    ctx.session.messages.append({"role": "assistant", "content": "hi, how can I help?"})
    from ai_cli import session as session_mod

    session_mod.save_session(ctx.session)
    session_id = ctx.session.id
    ctx.session = None  # simulate a fresh process needing to switch back in

    result = cmd_session(ctx, f"switch {session_id}")
    assert "Switched to session" in result
    assert "hello there" in result
    assert "hi, how can I help?" in result


def test_session_switch_reports_no_messages_yet(ctx):
    cmd_session(ctx, "new empty-session")
    session_id = ctx.session.id
    ctx.session = None

    result = cmd_session(ctx, f"switch {session_id}")
    assert "no messages yet" in result
