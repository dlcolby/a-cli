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
    # v1 keeps this a plain string. Tool-call/tool-result exchanges are
    # represented as synthetic text turns (see skills.py / repl.py's tool loop)
    # rather than provider-native structured content blocks, to avoid needing
    # a different Message shape per provider. Revisit if richer tool use is added.
    content: str


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
