from unittest.mock import MagicMock, patch

from ai_cli import ui
from ai_cli.context import AppContext


def _make_ctx(mouse_mode="auto"):
    ctx = MagicMock(spec=AppContext)
    ctx.mouse_mode = mouse_mode
    return ctx


def test_auto_mode_enables_mouse_when_completion_menu_open():
    ctx = _make_ctx("auto")
    repl_ui = ui.Repl_UI.__new__(ui.Repl_UI)  # bypass __init__ (needs a real terminal)
    repl_ui.ctx = ctx

    fake_app = MagicMock()
    buf = MagicMock()
    buf.complete_state = object()  # non-None means a dropdown is open

    with patch("ai_cli.ui.get_app", return_value=fake_app):
        repl_ui._on_completions_changed(buf)

    fake_app.output.enable_mouse_support.assert_called_once()
    fake_app.output.disable_mouse_support.assert_not_called()


def test_auto_mode_disables_mouse_when_completion_menu_closed():
    ctx = _make_ctx("auto")
    repl_ui = ui.Repl_UI.__new__(ui.Repl_UI)
    repl_ui.ctx = ctx

    fake_app = MagicMock()
    buf = MagicMock()
    buf.complete_state = None

    with patch("ai_cli.ui.get_app", return_value=fake_app):
        repl_ui._on_completions_changed(buf)

    fake_app.output.disable_mouse_support.assert_called_once()
    fake_app.output.enable_mouse_support.assert_not_called()


def test_fixed_modes_never_toggle_dynamically():
    for mode in ("on", "off"):
        ctx = _make_ctx(mode)
        repl_ui = ui.Repl_UI.__new__(ui.Repl_UI)
        repl_ui.ctx = ctx

        fake_app = MagicMock()
        buf = MagicMock()
        buf.complete_state = object()

        with patch("ai_cli.ui.get_app", return_value=fake_app):
            repl_ui._on_completions_changed(buf)

        fake_app.output.enable_mouse_support.assert_not_called()
        fake_app.output.disable_mouse_support.assert_not_called()
