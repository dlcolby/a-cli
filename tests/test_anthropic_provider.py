from unittest.mock import MagicMock, patch

from ai_cli.providers.anthropic_provider import AnthropicProvider
from ai_cli.providers.base import Message


def _sse_lines(*events):
    """events: list of (event_type, data_dict)"""
    lines = []
    for event_type, data in events:
        lines.append(f"event: {event_type}")
        lines.append(f"data: {__import__('json').dumps(data)}")
        lines.append("")
    return lines


def test_streaming_text_delta_parsing():
    provider = AnthropicProvider(api_key="fake")
    fake_lines = _sse_lines(
        ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "Hello"}}),
        ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": " world"}}),
        ("content_block_stop", {"index": 0}),
        ("message_delta", {"delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 5}}),
        ("message_stop", {}),
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = fake_lines

    with patch("ai_cli.providers.anthropic_provider.requests.post", return_value=mock_resp):
        events = list(provider.send("sonnet", "sys", [Message(role="user", content="hi")]))

    texts = [e.text for e in events if e.type == "text_delta"]
    assert texts == ["Hello", " world"]
    assert any(e.type == "message_stop" for e in events)
    assert any(e.type == "usage" and e.usage["output_tokens"] == 5 for e in events)


def test_streaming_tool_call_parsing():
    provider = AnthropicProvider(api_key="fake")
    fake_lines = _sse_lines(
        ("content_block_start", {"index": 0, "content_block": {"type": "tool_use", "id": "t1", "name": "read_skill"}}),
        ("content_block_delta", {"index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"name":'}}),
        ("content_block_delta", {"index": 0, "delta": {"type": "input_json_delta", "partial_json": '"foo"}'}}),
        ("content_block_stop", {"index": 0}),
        ("message_stop", {}),
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = fake_lines

    with patch("ai_cli.providers.anthropic_provider.requests.post", return_value=mock_resp):
        events = list(provider.send("sonnet", "sys", [Message(role="user", content="hi")]))

    tool_calls = [e.tool_call for e in events if e.type == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "read_skill"
    assert tool_calls[0].input == {"name": "foo"}


def test_non_streaming_response():
    provider = AnthropicProvider(api_key="fake")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "content": [{"type": "text", "text": "hi there"}],
        "usage": {"output_tokens": 2},
    }
    with patch("ai_cli.providers.anthropic_provider.requests.post", return_value=mock_resp):
        events = list(provider.send("sonnet", "sys", [Message(role="user", content="hi")], stream=False))
    texts = [e.text for e in events if e.type == "text_delta"]
    assert texts == ["hi there"]


def test_error_response():
    provider = AnthropicProvider(api_key="fake")
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.json.return_value = {"error": {"message": "invalid key"}}
    with patch("ai_cli.providers.anthropic_provider.requests.post", return_value=mock_resp):
        events = list(provider.send("sonnet", "sys", [Message(role="user", content="hi")]))
    assert events[0].type == "error"
    assert "invalid key" in events[0].error


def test_model_alias_resolution():
    provider = AnthropicProvider(api_key="fake")
    assert provider.resolve_model("sonnet") == "claude-sonnet-5"
    assert provider.resolve_model("claude-sonnet-5") == "claude-sonnet-5"
