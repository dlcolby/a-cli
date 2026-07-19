import asyncio
from unittest.mock import AsyncMock, MagicMock

from ai_cli import ui


def _make_repl_ui(mouse_mode="auto", complete_state=None):
    repl_ui = ui.Repl_UI.__new__(ui.Repl_UI)  # bypass __init__ (needs a real terminal)
    ctx = MagicMock()
    ctx.mouse_mode = mouse_mode
    repl_ui.ctx = ctx
    repl_ui.session = MagicMock()
    repl_ui.session.prompt_async = AsyncMock()
    repl_ui.session.default_buffer.complete_state = complete_state
    repl_ui._mouse_currently_on = False
    return repl_ui


def test_auto_mode_enables_mouse_when_dropdown_open():
    repl_ui = _make_repl_ui("auto", complete_state=object())
    repl_ui._sync_mouse_state(repl_ui.session.app)
    repl_ui.session.app.output.enable_mouse_support.assert_called_once()
    repl_ui.session.app.output.disable_mouse_support.assert_not_called()
    assert repl_ui._mouse_currently_on is True


def test_auto_mode_disables_mouse_when_dropdown_closes():
    repl_ui = _make_repl_ui("auto", complete_state=None)
    repl_ui._mouse_currently_on = True  # simulate it was on from a prior dropdown
    repl_ui._sync_mouse_state(repl_ui.session.app)
    repl_ui.session.app.output.disable_mouse_support.assert_called_once()
    repl_ui.session.app.output.enable_mouse_support.assert_not_called()
    assert repl_ui._mouse_currently_on is False


def test_no_redundant_calls_when_state_unchanged():
    repl_ui = _make_repl_ui("auto", complete_state=object())
    repl_ui._mouse_currently_on = True  # already on, matches complete_state != None
    repl_ui._sync_mouse_state(repl_ui.session.app)
    repl_ui.session.app.output.enable_mouse_support.assert_not_called()
    repl_ui.session.app.output.disable_mouse_support.assert_not_called()


def test_fixed_modes_never_toggle_dynamically():
    for mode in ("on", "off"):
        repl_ui = _make_repl_ui(mode, complete_state=object())
        repl_ui._sync_mouse_state(repl_ui.session.app)
        repl_ui.session.app.output.enable_mouse_support.assert_not_called()
        repl_ui.session.app.output.disable_mouse_support.assert_not_called()


def test_prompt_hard_resets_mouse_off_in_auto_mode_after_call():
    repl_ui = _make_repl_ui("auto")
    repl_ui.session.prompt_async.return_value = "hello"
    with __import__("unittest.mock", fromlist=["patch"]).patch("ai_cli.ui.build_completer", return_value=None):
        result = asyncio.run(repl_ui.prompt())
    assert result == "hello"
    repl_ui.session.app.output.disable_mouse_support.assert_called_once()
    assert repl_ui._mouse_currently_on is False


def test_prompt_does_not_force_disable_in_fixed_on_mode():
    repl_ui = _make_repl_ui("on")
    repl_ui.session.prompt_async.return_value = "hello"
    with __import__("unittest.mock", fromlist=["patch"]).patch("ai_cli.ui.build_completer", return_value=None):
        asyncio.run(repl_ui.prompt())
    repl_ui.session.app.output.disable_mouse_support.assert_not_called()


def test_prompt_uses_prompt_async_not_sync_prompt():
    # Regression: the sync prompt() wraps every call in its own asyncio.run(),
    # creating/tearing down a fresh event loop and kqueue selector each turn
    # -- the leading theory for a device crash (OSError: Errno 22 from
    # selectors.py) that surfaced on an ordinary prompt() call several turns
    # into a session. prompt_async() lets main() hold one event loop for the
    # REPL's whole lifetime instead.
    repl_ui = _make_repl_ui("off")
    repl_ui.session.prompt_async.return_value = "hello"
    with __import__("unittest.mock", fromlist=["patch"]).patch("ai_cli.ui.build_completer", return_value=None):
        asyncio.run(repl_ui.prompt())
    repl_ui.session.prompt_async.assert_awaited_once()
    repl_ui.session.prompt.assert_not_called()
