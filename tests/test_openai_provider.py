import json
from unittest.mock import MagicMock, patch

from ai_cli.providers.base import Message
from ai_cli.providers.openai_provider import OpenAIProvider


def _sse_lines(*payloads):
    lines = []
    for p in payloads:
        lines.append(f"data: {json.dumps(p) if p != '[DONE]' else '[DONE]'}")
        lines.append("")
    return lines


def test_streaming_text_delta():
    provider = OpenAIProvider(api_key="fake")
    fake_lines = _sse_lines(
        {"choices": [{"delta": {"content": "Hi"}}]},
        {"choices": [{"delta": {"content": " there"}}]},
        "[DONE]",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = fake_lines
    with patch("ai_cli.providers.openai_provider.requests.post", return_value=mock_resp):
        events = list(provider.send("gpt5", "sys", [Message(role="user", content="hi")]))
    texts = [e.text for e in events if e.type == "text_delta"]
    assert texts == ["Hi", " there"]
    assert events[-1].type == "message_stop"


def test_streaming_tool_call_accumulation():
    provider = OpenAIProvider(api_key="fake")
    fake_lines = _sse_lines(
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "read_skill", "arguments": ""}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"name":'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"foo"}'}}]}}]},
        "[DONE]",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = fake_lines
    with patch("ai_cli.providers.openai_provider.requests.post", return_value=mock_resp):
        events = list(provider.send("gpt5", "sys", [Message(role="user", content="hi")]))
    tool_calls = [e.tool_call for e in events if e.type == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "read_skill"
    assert tool_calls[0].input == {"name": "foo"}
