import json
from unittest.mock import MagicMock, patch

from ai_cli.providers.base import Message, text_block, tool_result_block, tool_use_block
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


def test_to_openai_messages_plain_string_passthrough():
    messages = [Message(role="user", content="hi")]
    assert OpenAIProvider._to_openai_messages(messages) == [{"role": "user", "content": "hi"}]


def test_to_openai_messages_translates_tool_use_to_tool_calls():
    messages = [
        Message(role="user", content="run it"),
        Message(
            role="assistant",
            content=[text_block("sure"), tool_use_block("t1", "run_command", {"command": "ls"})],
        ),
        Message(role="user", content=[tool_result_block("t1", "file1\nfile2")]),
    ]
    out = OpenAIProvider._to_openai_messages(messages)

    assert out[0] == {"role": "user", "content": "run it"}

    assistant_msg = out[1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == "sure"
    assert len(assistant_msg["tool_calls"]) == 1
    tc = assistant_msg["tool_calls"][0]
    assert tc["id"] == "t1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "run_command"
    assert json.loads(tc["function"]["arguments"]) == {"command": "ls"}

    tool_msg = out[2]
    assert tool_msg == {"role": "tool", "tool_call_id": "t1", "content": "file1\nfile2"}


def test_to_openai_messages_tool_call_with_no_text_has_null_content():
    messages = [Message(role="assistant", content=[tool_use_block("t1", "read_file", {"path": "a.py"})])]
    out = OpenAIProvider._to_openai_messages(messages)
    assert out[0]["content"] is None
    assert out[0]["tool_calls"][0]["function"]["name"] == "read_file"


def test_to_openai_messages_error_tool_result_is_prefixed():
    messages = [Message(role="user", content=[tool_result_block("t1", "boom", is_error=True)])]
    out = OpenAIProvider._to_openai_messages(messages)
    assert out[0] == {"role": "tool", "tool_call_id": "t1", "content": "Error: boom"}
