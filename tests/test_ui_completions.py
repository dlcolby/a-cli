from prompt_toolkit.document import Document

from ai_cli import session as session_mod, ui
from ai_cli.context import AppContext
from ai_cli import config as config_mod
from ai_cli.providers.anthropic_provider import AnthropicProvider


def _make_ctx(tmp_path):
    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    return AppContext(
        config=config_mod.Config(bookmark_root=str(bookmark)),
        cwd=bookmark,
        bookmark_root=bookmark,
        project_dir=None,
        provider_name="anthropic",
        provider=AnthropicProvider(api_key="fake"),
        model="sonnet",
    )


def test_mouse_dropdown_includes_auto(tmp_path):
    ctx = _make_ctx(tmp_path)
    completer = ui.build_completer(ctx)
    doc = Document("/mouse ", cursor_position=len("/mouse "))
    completions = {c.text for c in completer.get_completions(doc, None)}
    assert {"auto", "on", "off"} <= completions


def test_session_switch_dropdown_shows_timestamp_and_title(tmp_path):
    ctx = _make_ctx(tmp_path)
    s = session_mod.create_session(
        ctx.cwd, ctx.bookmark_root, "anthropic", "sonnet", title="a real title", global_scope=True
    )

    completer = ui._session_words(ctx)
    completions = list(completer.get_completions(Document(""), None))
    assert len(completions) == 1
    # The inserted text (on tap/selection) must still be the real id, for
    # switch/rm matching — but the visible label shows timestamp + title,
    # not the id's own (now title-free) hash suffix.
    assert completions[0].text == s.id
    assert "a real title" in completions[0].display_text
    assert s.id not in completions[0].display_text


def test_session_id_no_longer_bakes_in_title_slug(tmp_path):
    ctx = _make_ctx(tmp_path)
    s = session_mod.create_session(ctx.cwd, ctx.bookmark_root, "anthropic", "sonnet", global_scope=True)
    assert "untitled" not in s.id
