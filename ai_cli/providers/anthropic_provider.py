"""Anthropic provider: raw requests + hand-parsed SSE, no SDK (SDK deps are not
guaranteed pure-Python; raw HTTP keeps this a-shell-safe)."""

from __future__ import annotations

import json
from typing import Iterator, Optional

import requests

from .base import Message, ModelInfo, Provider, ProviderError, StreamEvent, ToolCall, ToolDef

API_VERSION = "2023-06-01"
DEFAULT_BASE_URL = "https://api.anthropic.com"

MODEL_ALIASES = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
    "fable": "claude-fable-5",
}


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        super().__init__(api_key, base_url or DEFAULT_BASE_URL)

    def list_models(self) -> list[ModelInfo]:
        """Live-query the models actually available to this API key, rather than
        a fixed guess — falls back to the curated aliases if the call fails
        (e.g. offline, invalid key)."""
        try:
            resp = requests.get(f"{self.base_url}/v1/models", headers=self._headers(), timeout=15)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if data:
                return [ModelInfo(alias=m["id"], model_id=m["id"]) for m in data]
        except requests.RequestException:
            pass
        return [ModelInfo(alias=alias, model_id=model_id) for alias, model_id in MODEL_ALIASES.items()]

    def resolve_model(self, alias_or_id: str) -> str:
        return MODEL_ALIASES.get(alias_or_id, alias_or_id)

    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }

    def _body(self, model: str, system: str, messages: list[Message], tools, stream: bool) -> dict:
        body = {
            "model": self.resolve_model(model),
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
        }
        if tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]
        return body

    def send(
        self,
        model: str,
        system: str,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        stream: bool = True,
    ) -> Iterator[StreamEvent]:
        url = f"{self.base_url}/v1/messages"
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

        event_type = None
        # Track partial tool_use blocks (accumulated JSON deltas) keyed by block index.
        tool_blocks: dict[int, dict] = {}
        for raw_line in resp.iter_lines(decode_unicode=True):
            if raw_line is None or raw_line == "":
                continue
            if raw_line.startswith("event:"):
                event_type = raw_line[len("event:") :].strip()
                continue
            if not raw_line.startswith("data:"):
                continue
            payload = json.loads(raw_line[len("data:") :].strip())

            if event_type == "content_block_start":
                block = payload.get("content_block", {})
                if block.get("type") == "tool_use":
                    tool_blocks[payload["index"]] = {
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "partial_json": "",
                    }
            elif event_type == "content_block_delta":
                delta = payload.get("delta", {})
                if delta.get("type") == "text_delta":
                    yield StreamEvent(type="text_delta", text=delta.get("text", ""))
                elif delta.get("type") == "input_json_delta":
                    idx = payload["index"]
                    if idx in tool_blocks:
                        tool_blocks[idx]["partial_json"] += delta.get("partial_json", "")
            elif event_type == "content_block_stop":
                idx = payload.get("index")
                if idx in tool_blocks:
                    tb = tool_blocks.pop(idx)
                    try:
                        tool_input = json.loads(tb["partial_json"]) if tb["partial_json"] else {}
                    except json.JSONDecodeError:
                        tool_input = {}
                    yield StreamEvent(
                        type="tool_call",
                        tool_call=ToolCall(id=tb["id"], name=tb["name"], input=tool_input),
                    )
            elif event_type == "message_delta":
                usage = payload.get("usage")
                if usage:
                    yield StreamEvent(type="usage", usage=usage)
            elif event_type == "message_stop":
                yield StreamEvent(type="message_stop")

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
        for block in data.get("content", []):
            if block.get("type") == "text":
                yield StreamEvent(type="text_delta", text=block.get("text", ""))
            elif block.get("type") == "tool_use":
                yield StreamEvent(
                    type="tool_call",
                    tool_call=ToolCall(id=block.get("id"), name=block.get("name"), input=block.get("input", {})),
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
