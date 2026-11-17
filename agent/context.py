"""Per-task context management: truncation, stubbing of old results, summarization."""
from __future__ import annotations

import json
from typing import Callable

from agent.prompts import SUMMARIZE_PROMPT
from agent.providers import Provider, ProviderError

KEEP_RECENT_FOR_STUB = 6
STUB_MIN_CHARS = 500
KEEP_RECENT_FOR_SUMMARY = 8
MIN_OLD_FOR_SUMMARY = 4
TRIGGER_RATIO = 0.8
SUMMARY_PREFIX = "[Task state summary]"
STUB_PREFIX = "[old "


def truncate_output(text: str, limit: int) -> str:
    """Keep head and tail of text, with a note of how much was omitted."""
    if len(text) <= limit:
        return text
    head = int(limit * 0.6)
    tail = limit - head
    omitted = len(text) - limit
    return f"{text[:head]}\n... [omitted {omitted} chars of {len(text)} total] ...\n{text[len(text) - tail:]}"


def estimate_tokens(messages: list[dict]) -> int:
    return sum(len(json.dumps(m, default=str)) for m in messages) // 4


def _tool_names(messages: list[dict]) -> dict[str, str]:
    names = {}
    for m in messages:
        for tc in m.get("tool_calls") or []:
            names[tc["id"]] = tc["function"]["name"]
    return names


class ContextManager:
    def __init__(self, provider: Provider, settings, warn: Callable[[str], None] | None = None):
        self.provider = provider
        self.settings = settings
        self.warn = warn or (lambda msg: None)
        self.last_usage: int | None = None
        self._suppress_until: float | None = None
        self._warned_over_budget = False

    # ---- task lifecycle ----
    def start_task(self, system_prompt: str, project_summary: str, user_request: str) -> list[dict]:
        """Brand-new history: nothing from earlier tasks except the short project summary."""
        self.last_usage = None
        self._suppress_until = None
        self._warned_over_budget = False
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Project summary:\n{project_summary}\n\nTask:\n{user_request}"},
        ]

    def add_tool_result(self, messages: list[dict], tool_call_id: str, content: str) -> None:
        # Tools already cut each output stream to output_limit_chars; this backstop allows two
        # streams (stdout and stderr) plus headers, so it never cuts a stream a second time.
        limit = self.settings.output_limit_chars * 2 + 200
        messages.append({"role": "tool", "tool_call_id": tool_call_id,
                         "content": truncate_output(content, limit)})

    def note_usage(self, total_tokens: int | None) -> None:
        self.last_usage = total_tokens

    # ---- per-step preparation ----
    def prepare(self, messages: list[dict]) -> list[dict]:
        messages = self._stub_old_results(messages)
        budget = self.settings.context_budget_tokens
        estimate = max(estimate_tokens(messages), self.last_usage or 0)
        if estimate <= TRIGGER_RATIO * budget:
            return messages
        if self._suppress_until is not None and estimate <= self._suppress_until:
            return messages
        return self._summarize(messages, budget)

    def _stub_old_results(self, messages: list[dict]) -> list[dict]:
        names = _tool_names(messages)
        out = []
        boundary = len(messages) - KEEP_RECENT_FOR_STUB
        for i, m in enumerate(messages):
            content = m.get("content")
            if (m.get("role") == "tool" and i < boundary and isinstance(content, str)
                    and len(content) > STUB_MIN_CHARS and not content.startswith(STUB_PREFIX)):
                name = names.get(m.get("tool_call_id"), "tool")
                first = content[:80].replace("\n", " ")
                m = {**m, "content": f"{STUB_PREFIX}{name} result omitted: {first}... ({len(content)} chars)]"}
            out.append(m)
        return out

    def _summarize(self, messages: list[dict], budget: int) -> list[dict]:
        first_user = next((i for i, m in enumerate(messages) if m.get("role") == "user"), None)
        if first_user is None:
            return messages
        cut = len(messages) - KEEP_RECENT_FOR_SUMMARY
        while cut > first_user + 1 and messages[cut].get("role") == "tool":
            cut -= 1  # keep an assistant tool_calls message together with its results
        old = messages[first_user + 1:cut]
        real_old = [m for m in old if not str(m.get("content") or "").startswith(SUMMARY_PREFIX)]
        if len(real_old) < MIN_OLD_FOR_SUMMARY:
            self._warn_over_budget()
            return messages
        recent = messages[cut:]
        try:
            note = self.provider.complete(
                [{"role": "system", "content": SUMMARIZE_PROMPT},
                 {"role": "user", "content": self._render(old)}], []).text or ""
            note = note.strip() or self._fallback_note(old, "empty summary")
        except ProviderError as exc:
            note = self._fallback_note(old, str(exc))
            self.warn(f"context summary failed: {exc}")
        new = [*messages[:first_user + 1],
               {"role": "user", "content": f"{SUMMARY_PREFIX}\n{note}"}, *recent]
        self.last_usage = None
        post = estimate_tokens(new)
        self._suppress_until = post * 1.2 if post > TRIGGER_RATIO * budget else None
        if post > budget:
            self._warn_over_budget()
        return new

    @staticmethod
    def _render(old: list[dict]) -> str:
        lines = []
        for m in old:
            role = m.get("role")
            content = str(m.get("content") or "")
            if role == "tool":
                content = truncate_output(content, 200)
            lines.append(f"{role}: {content}")
            for tc in m.get("tool_calls") or []:
                lines.append(f"  call {tc['function']['name']}({tc['function']['arguments'][:200]})")
        return "\n".join(lines)

    @staticmethod
    def _fallback_note(old: list[dict], error: str) -> str:
        paths: list[str] = []
        for m in old:
            for tc in m.get("tool_calls") or []:
                if tc["function"]["name"] in ("write_file", "edit_file"):
                    try:
                        p = json.loads(tc["function"]["arguments"]).get("path")
                    except (ValueError, AttributeError):
                        continue
                    if isinstance(p, str) and p not in paths:
                        paths.append(p)
        files = "\n".join(f"- {p}" for p in paths) or "- (none)"
        return f"Files touched:\n{files}\n(summary unavailable: {error})"

    def _warn_over_budget(self) -> None:
        if not self._warned_over_budget:
            self._warned_over_budget = True
            self.warn("context is still over the token budget; the provider may reject the next call")
