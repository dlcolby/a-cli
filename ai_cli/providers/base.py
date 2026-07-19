"""Provider abstraction. This ABC — not a third-party SDK like litellm — is the
LLM-agnostic mechanism for this project. litellm was evaluated and rejected: it
hard-depends on tiktoken/tokenizers (Rust/PyO3) and pydantic>=2 (pydantic-core is
Rust), none of which can build under a-shell's pure-Python-only pip. Keeping this
layer thin and dependency-free avoids that whole class of problem.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator, Optional


@dataclass
class Message:
    role: str  # "user" | "assistant"
    # Plain text turns keep content as a str. Turns involving tool use carry a
    # list of content blocks instead, mirroring Anthropic's native block shape
    # (each dict has a "type": "text" | "tool_use" | "tool_result", plus that
    # type's fields — see the *_block() helpers below). Anthropic's wire format
    # accepts this shape directly; OpenAIProvider translates it to Chat
    # Completions' tool_calls/"tool"-role-message shape in its own _body().
    content: str | list[dict]


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def tool_use_block(id: str, name: str, input: dict) -> dict:
    return {"type": "tool_use", "id": id, "name": name, "input": input}


def tool_result_block(tool_use_id: str, content: str, is_error: bool = False) -> dict:
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        block["is_error"] = True
    return block


def content_to_text(content: str | list[dict]) -> str:
    """Flatten either shape of Message.content into a plain string, for
    contexts that only care about human-readable text: the session's markdown
    mirror, /session switch's transcript reprint, and session auto-naming."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "tool_use":
            parts.append(f"[tool call] {block.get('name')}({block.get('input')})")
        elif btype == "tool_result":
            label = "tool error" if block.get("is_error") else "tool result"
            parts.append(f"[{label}] {block.get('content', '')}")
        else:
            parts.append(str(block))
    return "\n".join(parts)


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class StreamEvent:
    type: str  # "text_delta" | "tool_call" | "message_stop" | "usage" | "error"
    text: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    usage: Optional[dict] = None
    error: Optional[str] = None


@dataclass
class ModelInfo:
    alias: str
    model_id: str


class ProviderError(RuntimeError):
    pass


class Provider(ABC):
    name: str = "base"

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = base_url

    @abstractmethod
    def list_models(self) -> list[ModelInfo]:
        ...

    @abstractmethod
    def send(
        self,
        model: str,
        system: str,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        stream: bool = True,
    ) -> Iterator[StreamEvent]:
        """Send a chat turn. Yields StreamEvent objects as they arrive.

        If stream=False, implementations should still yield StreamEvent objects
        (just all at once, after the full response arrives) so callers never
        branch on streaming mode.
        """
        ...
