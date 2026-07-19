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


def test_read_file_tool_call_needs_no_confirmation(tmp_path):
    provider = FakeProvider(
        [
            [StreamEvent(type="tool_call", tool_call=ToolCall(id="t1", name="read_file", input={"path": "f.txt"}))],
            [StreamEvent(type="text_delta", text="done")],
        ]
    )
    ctx = make_ctx(tmp_path, provider)
    (ctx.bookmark_root / "f.txt").write_text("hello", encoding="utf-8")

    repl.send_turn(ctx, "read the file")

    assert ctx.pending_confirmation is None  # never needed to pause
    msgs = ctx.session.messages
    assert msgs[0] == {"role": "user", "content": "read the file"}
    assert msgs[1]["content"][0]["type"] == "tool_use"
    assert msgs[1]["content"][0]["name"] == "read_file"
    result_block = msgs[2]["content"][0]
    assert result_block["type"] == "tool_result"
    assert result_block["content"] == "hello"
    assert "is_error" not in result_block
    assert msgs[3] == {"role": "assistant", "content": "done"}


def test_write_file_pauses_for_confirmation_instead_of_blocking(tmp_path):
    # The whole point of the current design: send_turn() must never block for
    # input mid-turn (five device round-trips of nested/synchronous reads all
    # hung or crashed on-device). It pauses, storing resumable state, and
    # returns control to the caller instead.
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

    repl.send_turn(ctx, "write a file")

    assert ctx.pending_confirmation is not None
    assert not (ctx.bookmark_root / "out.txt").exists()
    assert provider.calls == 1  # never made a second network call while paused


def test_write_file_declined_is_not_written(tmp_path):
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

    repl.resume_pending_confirmation(ctx, "n")

    assert ctx.pending_confirmation is None
    assert not (ctx.bookmark_root / "out.txt").exists()
    result_block = ctx.session.messages[2]["content"][0]
    assert result_block["is_error"] is True
    assert result_block["content"] == "User declined to run this tool call."
    assert ctx.session.messages[-1] == {"role": "assistant", "content": "ok, stopping"}


def test_declining_with_a_reason_passes_it_back_as_feedback(tmp_path):
    # Anything other than a bare y/yes/n/no/empty reply is treated as a
    # decline *with* feedback, so the user can redirect instead of just
    # rejecting outright.
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    type="tool_call",
                    tool_call=ToolCall(id="t1", name="run_command", input={"command": "find ."}),
                )
            ],
            [StreamEvent(type="text_delta", text="ok, trying that instead")],
        ]
    )
    ctx = make_ctx(tmp_path, provider)
    repl.send_turn(ctx, "find the readme")

    repl.resume_pending_confirmation(ctx, "no, use -maxdepth 2 instead")

    result_block = ctx.session.messages[2]["content"][0]
    assert result_block["is_error"] is True
    assert result_block["content"] == "User declined to run this tool call and said: no, use -maxdepth 2 instead"


def test_write_file_approved_writes_to_project_root(tmp_path):
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

    repl.resume_pending_confirmation(ctx, "y")

    assert ctx.pending_confirmation is None
    assert (ctx.bookmark_root / "out.txt").read_text(encoding="utf-8") == "hi"
    result_block = ctx.session.messages[2]["content"][0]
    assert "is_error" not in result_block


def test_confirmation_reply_is_case_insensitive_and_trims_whitespace(tmp_path):
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

    repl.resume_pending_confirmation(ctx, "  YES  ")

    assert (ctx.bookmark_root / "out.txt").read_text(encoding="utf-8") == "hi"


def test_path_escape_attempt_is_reported_as_tool_error(tmp_path):
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

    repl.resume_pending_confirmation(ctx, "y")

    assert not (ctx.bookmark_root.parent / "escape.txt").exists()
    result_block = ctx.session.messages[2]["content"][0]
    assert result_block["is_error"] is True
    assert "escapes" in result_block["content"]


def test_multiple_tool_calls_in_one_round_only_pauses_for_the_confirm_needed_one(tmp_path):
    # read_file executes immediately; write_file pauses. Order must be
    # preserved in the eventual combined tool_result message.
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    type="tool_call", tool_call=ToolCall(id="t1", name="read_file", input={"path": "f.txt"})
                ),
                StreamEvent(
                    type="tool_call",
                    tool_call=ToolCall(id="t2", name="write_file", input={"path": "out.txt", "content": "hi"}),
                ),
            ],
            [StreamEvent(type="text_delta", text="done")],
        ]
    )
    ctx = make_ctx(tmp_path, provider)
    (ctx.bookmark_root / "f.txt").write_text("hello", encoding="utf-8")

    repl.send_turn(ctx, "read then write")

    assert ctx.pending_confirmation is not None
    assert ctx.pending_confirmation["remaining_tool_calls"][0].id == "t2"
    assert ctx.pending_confirmation["result_blocks"][0]["content"] == "hello"  # read_file already ran

    repl.resume_pending_confirmation(ctx, "y")

    result_blocks = ctx.session.messages[2]["content"]
    assert result_blocks[0]["content"] == "hello"
    assert "is_error" not in result_blocks[1]
    assert (ctx.bookmark_root / "out.txt").exists()


def test_session_round_trips_through_save_and_load(tmp_path):
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
    repl.resume_pending_confirmation(ctx, "y")

    from ai_cli import session as session_mod

    loaded = session_mod.load_session(ctx.session.path)
    assert loaded.messages == ctx.session.messages

    # markdown mirror must render structured content without crashing
    from pathlib import Path

    md = Path(ctx.session.path).with_suffix(".md").read_text(encoding="utf-8")
    assert "write_file" in md


def test_session_saved_incrementally_survives_mid_turn_crash(tmp_path):
    # Regression: a device crash mid-turn (during the network call for round
    # 2, after the tool from round 1 already ran) wiped out the whole
    # exchange, including the user's original request, because save_session()
    # only ran at the very end of send_turn(). Each round must persist as it
    # completes so a later crash doesn't lose earlier rounds.
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

    provider.send = send_wrapper

    repl.send_turn(ctx, "write a file")
    assert ctx.pending_confirmation is not None

    try:
        repl.resume_pending_confirmation(ctx, "y")
    except RuntimeError:
        pass

    from ai_cli import session as session_mod

    loaded = session_mod.load_session(ctx.session.path)
    assert loaded.messages[0] == {"role": "user", "content": "write a file"}
    assert loaded.messages[1]["content"][0]["name"] == "write_file"
    assert loaded.messages[2]["content"][0]["type"] == "tool_result"
