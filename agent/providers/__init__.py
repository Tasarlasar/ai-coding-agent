"""Provider interface: the agent core only depends on this module."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    """A tool call requested by the model."""
    id: str
    name: str
    arguments: dict  # {"__parse_error": raw} when the raw string is not a JSON object
    raw_arguments: str


@dataclass
class Response:
    """A model reply: optional text, tool calls and token usage."""
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage_total_tokens: int | None = None


class ProviderError(Exception):
    """One-line, already scrubbed message."""


class Provider(Protocol):
    """Anything that can turn messages and tool schemas into a Response."""

    def complete(self, messages: list[dict], tools: list[dict]) -> Response:
        """Send messages and tool schemas to the model and return its reply."""
        ...
