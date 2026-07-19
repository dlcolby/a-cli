from ai_cli import repl
from ai_cli.context import AppContext
from ai_cli.providers.anthropic_provider import AnthropicProvider
from ai_cli.providers.base import StreamEvent, ToolCall


class FakeProvider(AnthropicProvider):
    """Scripted provider: each call to send() yields the next queued turn's
    events, regardless of what messages/tools were actually passed."""

    def __init__(self, turns):
        super().__init__(api_key="fake")
        self.turns = turns
        self.calls = 0

    def send(self, model, system, messages, tools=None, stream=True):
        turn = self.turns[self.calls]
        self.calls += 1
        yield from turn


def make_ctx(tmp_path, provider):
    from ai_cli import config as config_mod

    bookmark = tmp_path / "bookmark"
    bookmark.mkdir()
    return AppContext(
        config=config_mod.Config(bookmark_root=str(bookmark)),
        cwd=bookmark,
        bookmark_root=bookmark,
        project_dir=None,
        provider_name="anthropic",
        provider=provider,
        model="sonnet",
    )


def test_read_file_tool_call_needs_no_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: (_ for _ in ()).throw(AssertionError("should not prompt")))

    provider = FakeProvider(
        [
            [StreamEvent(type="tool_call", tool_call=ToolCall(id="t1", name="read_file", input={"path": "f.txt"}))],
            [StreamEvent(type="text_delta", text="done")],
        ]
    )
    ctx = make_ctx(tmp_path, provider)
    (ctx.bookmark_root / "f.txt").write_text("hello", encoding="utf-8")

    repl.send_turn(ctx, "read the file")

    msgs = ctx.session.messages
    assert msgs[0] == {"role": "user", "content": "read the file"}
    assert msgs[1]["content"][0]["type"] == "tool_use"
    assert msgs[1]["content"][0]["name"] == "read_file"
    result_block = msgs[2]["content"][0]
    assert result_block["type"] == "tool_result"
    assert result_block["content"] == "hello"
    assert "is_error" not in result_block
    assert msgs[3] == {"role": "assistant", "content": "done"}


def test_write_file_declined_is_not_written(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "n")

    provider = FakeProvider(
        [
            [
                StreamEvent(
                    type="tool_call",
                    tool_call=ToolCall(id="t1", name="write_file", input={"path": "out.txt", "content": "hi"}),
                )
            ],
            [StreamEvent(type="text_delta", text="ok, stopping")],
        ]
    )
    ctx = make_ctx(tmp_path, provider)

    repl.send_turn(ctx, "write a file")

    assert not (ctx.bookmark_root / "out.txt").exists()
    result_block = ctx.session.messages[2]["content"][0]
    assert result_block["is_error"] is True
    assert "declined" in result_block["content"]
    assert ctx.session.messages[-1] == {"role": "assistant", "content": "ok, stopping"}


def test_write_file_approved_writes_to_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "y")

    provider = FakeProvider(
        [
            [
                StreamEvent(
                    type="tool_call",
                    tool_call=ToolCall(id="t1", name="write_file", input={"path": "out.txt", "content": "hi"}),
                )
            ],
            [StreamEvent(type="text_delta", text="done")],
        ]
    )
    ctx = make_ctx(tmp_path, provider)

    repl.send_turn(ctx, "write a file")

    assert (ctx.bookmark_root / "out.txt").read_text(encoding="utf-8") == "hi"
    result_block = ctx.session.messages[2]["content"][0]
    assert "is_error" not in result_block


def test_path_escape_attempt_is_reported_as_tool_error(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "y")

    provider = FakeProvider(
        [
            [
                StreamEvent(
                    type="tool_call",
                    tool_call=ToolCall(
                        id="t1", name="write_file", input={"path": "../escape.txt", "content": "pwned"}
                    ),
                )
            ],
            [StreamEvent(type="text_delta", text="done")],
        ]
    )
    ctx = make_ctx(tmp_path, provider)

    repl.send_turn(ctx, "escape the sandbox")

    assert not (ctx.bookmark_root.parent / "escape.txt").exists()
    result_block = ctx.session.messages[2]["content"][0]
    assert result_block["is_error"] is True
    assert "escapes" in result_block["content"]


def test_session_round_trips_through_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "y")

    provider = FakeProvider(
        [
            [
                StreamEvent(
                    type="tool_call",
                    tool_call=ToolCall(id="t1", name="write_file", input={"path": "out.txt", "content": "hi"}),
                )
            ],
            [StreamEvent(type="text_delta", text="done")],
        ]
    )
    ctx = make_ctx(tmp_path, provider)
    repl.send_turn(ctx, "write a file")

    from ai_cli import session as session_mod

    loaded = session_mod.load_session(ctx.session.path)
    assert loaded.messages == ctx.session.messages

    # markdown mirror must render structured content without crashing
    from pathlib import Path

    md = Path(ctx.session.path).with_suffix(".md").read_text(encoding="utf-8")
    assert "write_file" in md


def test_session_saved_incrementally_survives_mid_turn_crash(tmp_path, monkeypatch):
    # Regression: a device crash mid-turn (during the network call for round
    # 2, after the tool from round 1 already ran) wiped out the whole
    # exchange, including the user's original request, because save_session()
    # only ran at the very end of send_turn(). Each round must persist as it
    # completes so a later crash doesn't lose earlier rounds.
    monkeypatch.setattr("builtins.input", lambda *a: "y")

    provider = FakeProvider(
        [
            [
                StreamEvent(
                    type="tool_call",
                    tool_call=ToolCall(id="t1", name="write_file", input={"path": "out.txt", "content": "hi"}),
                )
            ],
        ]
    )
    ctx = make_ctx(tmp_path, provider)
    original_send = provider.send
    calls = {"n": 0}

    def send_wrapper(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            yield from original_send(*args, **kwargs)
        else:
            raise RuntimeError("simulated mid-turn crash")
            yield  # pragma: no cover - unreachable, just makes this a generator function

    monkeypatch.setattr(provider, "send", send_wrapper)

    try:
        repl.send_turn(ctx, "write a file")
    except RuntimeError:
        pass

    from ai_cli import session as session_mod

    loaded = session_mod.load_session(ctx.session.path)
    assert loaded.messages[0] == {"role": "user", "content": "write a file"}
    assert loaded.messages[1]["content"][0]["name"] == "write_file"
    assert loaded.messages[2]["content"][0]["type"] == "tool_result"


def test_confirm_restores_pristine_termios_snapshot_when_available(tmp_path, monkeypatch):
    # Regression: an earlier version patched ICANON|ECHO onto whatever *live*
    # (possibly raw-mode) attrs were current, which froze the terminal
    # on-device -- POSIX termios reuses c_cc slots for different meanings
    # depending on ICANON, so patching lflags without resetting c_cc can
    # break canonical line-reading. The fix restores a full pristine
    # snapshot (captured before prompt_toolkit ever ran) instead.
    import sys as sys_mod
    from unittest.mock import MagicMock

    fake_termios = MagicMock()
    fake_termios.error = OSError
    fake_termios.TCSANOW = 0
    pristine_attrs = [0, 0, 0, 0o0000012, 0, 0, [0] * 32]  # captured at startup, before any raw mode
    live_attrs = [0, 0, 0, 0, 0, 0, [1] * 32]  # whatever raw state prompt_toolkit left behind
    fake_termios.tcgetattr.return_value = list(live_attrs)
    monkeypatch.setattr(repl, "termios", fake_termios)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    fake_stdin = MagicMock()
    fake_stdin.fileno.return_value = 0
    monkeypatch.setattr(sys_mod, "stdin", fake_stdin)  # pytest's captured stdin has no real fileno()

    ctx = make_ctx(tmp_path, provider=None)
    ctx.pristine_termios = pristine_attrs
    assert repl._confirm(ctx, "Allow write_file(...)?") is True

    assert fake_termios.tcsetattr.call_count == 2
    assert fake_termios.tcsetattr.call_args_list[0].args == (0, fake_termios.TCSANOW, pristine_attrs)
    assert fake_termios.tcsetattr.call_args_list[1].args == (0, fake_termios.TCSANOW, live_attrs)


def test_confirm_skips_termios_when_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(repl, "termios", None)
    monkeypatch.setattr("builtins.input", lambda *a: "n")

    ctx = make_ctx(tmp_path, provider=None)
    assert repl._confirm(ctx, "Allow?") is False


def test_confirm_skips_termios_when_no_pristine_snapshot_captured(tmp_path, monkeypatch):
    # e.g. main() couldn't snapshot stdin at startup (not a real tty) --
    # ctx.pristine_termios stays None, so don't touch termios at all.
    from unittest.mock import MagicMock

    fake_termios = MagicMock()
    monkeypatch.setattr(repl, "termios", fake_termios)
    monkeypatch.setattr("builtins.input", lambda *a: "y")

    ctx = make_ctx(tmp_path, provider=None)
    assert ctx.pristine_termios is None
    assert repl._confirm(ctx, "Allow?") is True
    fake_termios.tcgetattr.assert_not_called()
    fake_termios.tcsetattr.assert_not_called()
