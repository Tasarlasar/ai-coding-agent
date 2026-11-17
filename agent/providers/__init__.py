"""Provider interface: the agent core only depends on this module."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict  # {"__parse_error": raw} when the raw string is not a JSON object
    raw_arguments: str


@dataclass
class Response:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage_total_tokens: int | None = None


class ProviderError(Exception):
    """One-line, already scrubbed message."""


class Provider(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> Response: ...
