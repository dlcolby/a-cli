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
