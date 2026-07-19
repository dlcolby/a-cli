from unittest.mock import MagicMock

from ai_cli import ui


def _make_repl_ui(mouse_mode="auto", complete_state=None):
    repl_ui = ui.Repl_UI.__new__(ui.Repl_UI)  # bypass __init__ (needs a real terminal)
    ctx = MagicMock()
    ctx.mouse_mode = mouse_mode
    repl_ui.ctx = ctx
    repl_ui.session = MagicMock()
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
    repl_ui.session.prompt.return_value = "hello"
    with __import__("unittest.mock", fromlist=["patch"]).patch("ai_cli.ui.build_completer", return_value=None):
        result = repl_ui.prompt()
    assert result == "hello"
    repl_ui.session.app.output.disable_mouse_support.assert_called_once()
    assert repl_ui._mouse_currently_on is False


def test_prompt_does_not_force_disable_in_fixed_on_mode():
    repl_ui = _make_repl_ui("on")
    repl_ui.session.prompt.return_value = "hello"
    with __import__("unittest.mock", fromlist=["patch"]).patch("ai_cli.ui.build_completer", return_value=None):
        repl_ui.prompt()
    repl_ui.session.app.output.disable_mouse_support.assert_not_called()


def test_confirm_uses_prompt_session_not_bare_input():
    repl_ui = _make_repl_ui("on")
    repl_ui.session.prompt.return_value = "y"
    assert repl_ui.confirm("Allow run_command(...)?") is True
    repl_ui.session.prompt.assert_called_once()
    repl_ui.session.app.output.disable_mouse_support.assert_called_once()


def test_confirm_disables_completion_for_this_call():
    # Regression: confirm() reusing self.session's live NestedCompleter (plus
    # complete_while_typing=True, still set from the last regular prompt())
    # meant typing "y" popped a fuzzy-matched completion dropdown on-device,
    # which then tripped the auto-mouse crash below. Must pass completer=None
    # / complete_while_typing=False as per-call overrides rather than relying
    # on whatever the session was last configured with.
    repl_ui = _make_repl_ui("auto")
    repl_ui.session.prompt.return_value = "y"
    repl_ui.confirm("Allow write_file(...)?")
    _, kwargs = repl_ui.session.prompt.call_args
    assert kwargs["completer"] is None
    assert kwargs["complete_while_typing"] is False


def test_confirm_detaches_and_reattaches_auto_mouse_hook():
    # Regression: the on_invalidate auto-mouse hook doesn't know a given
    # prompt() call asked for mouse_support=False, so if it fires mid-call
    # (e.g. a dropdown appearing) it calls enable_mouse_support() on an
    # Application configured without mouse support -- the mismatch that
    # crashed a-shell's input registration (EINVAL) on-device. confirm()
    # must detach the hook for the duration and restore it afterward so
    # normal /mouse auto behavior resumes on the next regular prompt().
    repl_ui = _make_repl_ui("auto")
    repl_ui.session.prompt.return_value = "y"
    original_hook = repl_ui.session.app.on_invalidate  # -= rebinds the attribute, so grab it first
    repl_ui.confirm("Allow write_file(...)?")
    original_hook.__isub__.assert_called_once_with(repl_ui._sync_mouse_state)
    original_hook.__isub__.return_value.__iadd__.assert_called_once_with(repl_ui._sync_mouse_state)


def test_confirm_disables_mouse_even_in_fixed_on_mode():
    # Regression: fixed "on" mode leaves mouse tracking enabled across turns,
    # which is exactly the state a bare input() call couldn't handle
    # on-device. confirm() must force it off before prompting regardless of
    # ctx.mouse_mode.
    repl_ui = _make_repl_ui("on")
    repl_ui.session.prompt.return_value = "n"
    assert repl_ui.confirm("Allow write_file(...)?") is False
    repl_ui.session.app.output.disable_mouse_support.assert_called_once()
    repl_ui.session.app.output.flush.assert_called()


def test_confirm_rejects_anything_but_y_or_yes():
    repl_ui = _make_repl_ui("off")
    for answer, expected in [("", False), ("n", False), ("no", False), ("y", True), ("yes", True), ("Y", True)]:
        repl_ui.session.prompt.return_value = answer
        assert repl_ui.confirm("Allow?") is expected
