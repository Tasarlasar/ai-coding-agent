"""Scripted provider for offline tests."""
from __future__ import annotations

import copy

from agent.providers import Response


class FakeProvider:
    """Returns scripted responses in order and records the calls it received."""
    def __init__(self, script: list[Response]):
        self.script = list(script)
        self.calls: list[list[dict]] = []
        self.tools_seen: list[list[dict]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> Response:
        """Return the next scripted response, or raise it if it is an exception."""
        self.calls.append(copy.deepcopy(messages))
        self.tools_seen.append(tools)
        if not self.script:
            raise AssertionError("FakeProvider script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
