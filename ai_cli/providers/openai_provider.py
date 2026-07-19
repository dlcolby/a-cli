"""OpenAI provider: raw requests + hand-parsed SSE against the Chat Completions
API (chosen over the Responses API for v1 simplicity/stability)."""

from __future__ import annotations

import json
from typing import Iterator, Optional

import requests

from .base import Message, ModelInfo, Provider, StreamEvent, ToolCall, ToolDef

DEFAULT_BASE_URL = "https://api.openai.com"

MODEL_ALIASES = {
    "gpt5": "gpt-5",
    "gpt5-mini": "gpt-5-mini",
}

# The live /v1/models list includes embeddings, TTS, image, and other
# non-chat models this app has no use for — filtered out of the dropdown.
_NON_CHAT_MARKERS = (
    "embedding", "whisper", "tts", "dall-e", "moderation", "davinci",
    "babbage", "ada", "curie", "audio", "realtime", "transcribe", "image",
)


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        super().__init__(api_key, base_url or DEFAULT_BASE_URL)

    def list_models(self) -> list[ModelInfo]:
        """Live-query the models actually available to this API key, filtered
        to plausible chat models — falls back to the curated aliases if the
        call fails (e.g. offline, invalid key)."""
        try:
            resp = requests.get(f"{self.base_url}/v1/models", headers=self._headers(), timeout=15)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            ids = sorted(
                m["id"] for m in data if not any(marker in m["id"].lower() for marker in _NON_CHAT_MARKERS)
            )
            if ids:
                return [ModelInfo(alias=mid, model_id=mid) for mid in ids]
        except requests.RequestException:
            pass
        return [ModelInfo(alias=alias, model_id=model_id) for alias, model_id in MODEL_ALIASES.items()]

    def resolve_model(self, alias_or_id: str) -> str:
        return MODEL_ALIASES.get(alias_or_id, alias_or_id)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"}

    def _body(self, model: str, system: str, messages: list[Message], tools, stream: bool) -> dict:
        chat_messages = [{"role": "system", "content": system}] if system else []
        chat_messages += self._to_openai_messages(messages)
        body = {"model": self.resolve_model(model), "messages": chat_messages, "stream": stream}
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.input_schema},
                }
                for t in tools
            ]
        return body

    @staticmethod
    def _to_openai_messages(messages: list[Message]) -> list[dict]:
        """Translate our Anthropic-shaped content blocks (see providers/base.py)
        into Chat Completions' own shape: tool_use blocks become an assistant
        message's "tool_calls" array, tool_result blocks become separate
        "tool"-role messages (OpenAI has no user-role tool result, unlike
        Anthropic) keyed by tool_call_id."""
        out = []
        for m in messages:
            if isinstance(m.content, str):
                out.append({"role": m.role, "content": m.content})
                continue

            text_parts, tool_calls, tool_results = [], [], []
            for block in m.content:
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tool_calls.append(
                        {
                            "id": block["id"],
                            "type": "function",
                            "function": {"name": block["name"], "arguments": json.dumps(block.get("input", {}))},
                        }
                    )
                elif btype == "tool_result":
                    tool_results.append(block)

            if m.role == "assistant":
                assistant_msg = {"role": "assistant", "content": "".join(text_parts) or None}
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                out.append(assistant_msg)
            elif text_parts:
                out.append({"role": "user", "content": "".join(text_parts)})

            for tr in tool_results:
                content = tr.get("content", "")
                if tr.get("is_error"):
                    content = f"Error: {content}"
                out.append({"role": "tool", "tool_call_id": tr["tool_use_id"], "content": content})
        return out

    def send(
        self,
        model: str,
        system: str,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        stream: bool = True,
    ) -> Iterator[StreamEvent]:
        url = f"{self.base_url}/v1/chat/completions"
        body = self._body(model, system, messages, tools, stream)

        if not stream:
            yield from self._send_non_streaming(url, body)
            return

        try:
            resp = requests.post(url, headers=self._headers(), json=body, stream=True, timeout=(10, 300))
        except requests.RequestException as exc:
            yield StreamEvent(type="error", error=str(exc))
            return

        if resp.status_code != 200:
            yield StreamEvent(type="error", error=self._error_message(resp))
            return

        # Accumulate streamed tool-call fragments by index (OpenAI streams tool_calls
        # incrementally, split across chunks, unlike Anthropic's block-indexed deltas).
        tool_calls: dict[int, dict] = {}
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data:"):
                continue
            data_str = raw_line[len("data:") :].strip()
            if data_str == "[DONE]":
                for tc in tool_calls.values():
                    yield self._finalize_tool_call(tc)
                yield StreamEvent(type="message_stop")
                return
            payload = json.loads(data_str)
            choice = payload.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            if delta.get("content"):
                yield StreamEvent(type="text_delta", text=delta["content"])
            for tc_delta in delta.get("tool_calls", []) or []:
                idx = tc_delta["index"]
                tc = tool_calls.setdefault(idx, {"id": None, "name": None, "arguments": ""})
                if tc_delta.get("id"):
                    tc["id"] = tc_delta["id"]
                fn = tc_delta.get("function", {})
                if fn.get("name"):
                    tc["name"] = fn["name"]
                if fn.get("arguments"):
                    tc["arguments"] += fn["arguments"]
            if payload.get("usage"):
                yield StreamEvent(type="usage", usage=payload["usage"])

    def _finalize_tool_call(self, tc: dict) -> StreamEvent:
        try:
            tool_input = json.loads(tc["arguments"]) if tc["arguments"] else {}
        except json.JSONDecodeError:
            tool_input = {}
        return StreamEvent(type="tool_call", tool_call=ToolCall(id=tc["id"], name=tc["name"], input=tool_input))

    def _send_non_streaming(self, url: str, body: dict) -> Iterator[StreamEvent]:
        body = {**body, "stream": False}
        try:
            resp = requests.post(url, headers=self._headers(), json=body, timeout=(10, 300))
        except requests.RequestException as exc:
            yield StreamEvent(type="error", error=str(exc))
            return
        if resp.status_code != 200:
            yield StreamEvent(type="error", error=self._error_message(resp))
            return
        data = resp.json()
        message = data.get("choices", [{}])[0].get("message", {})
        if message.get("content"):
            yield StreamEvent(type="text_delta", text=message["content"])
        for tc in message.get("tool_calls", []) or []:
            try:
                tool_input = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                tool_input = {}
            yield StreamEvent(
                type="tool_call",
                tool_call=ToolCall(id=tc.get("id"), name=tc["function"]["name"], input=tool_input),
            )
        if data.get("usage"):
            yield StreamEvent(type="usage", usage=data["usage"])
        yield StreamEvent(type="message_stop")

    @staticmethod
    def _error_message(resp: requests.Response) -> str:
        try:
            return resp.json().get("error", {}).get("message", resp.text)
        except (ValueError, KeyError):
            return f"HTTP {resp.status_code}: {resp.text}"
