"""The agent loop: model call, tool calls, results, repeat."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from agent.prompts import SYSTEM_PROMPT
from agent.providers import Provider, ProviderError
from agent.tools import Tool, ToolContext, ToolResult, validate_args


@dataclass
class TaskResult:
    outcome: str  # done | step_limit | provider_error | interrupted | internal_error
    final_text: str | None
    steps: int


class AgentLoop:
    def __init__(self, provider: Provider, tools: dict[str, Tool], ctx: ToolContext,
                 max_steps: int, emit: Callable[[str, str], None],
                 confirm: Callable[[str], str] | None = None):
        self.provider = provider
        self.tools = tools
        self.ctx = ctx
        self.max_steps = max_steps
        self.emit = emit
        self.confirm = confirm or (lambda prompt: "no")
        self.schemas = [t.schema for t in tools.values()]

    def run_task(self, request: str) -> TaskResult:
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": request},
        ]
        outcome, final_text, steps = "step_limit", None, 0
        pending: list = []
        try:
            for steps in range(1, self.max_steps + 1):
                try:
                    resp = self.provider.complete(messages, self.schemas)
                except ProviderError as exc:
                    self.emit("error", str(exc))
                    outcome = "provider_error"
                    break
                messages.append(self._assistant_message(resp))
                if resp.text:
                    self.emit("assistant", resp.text)
                if not resp.tool_calls:
                    outcome, final_text = "done", resp.text
                    break
                pending = list(resp.tool_calls)
                while pending:
                    call = pending[0]
                    result = self._execute(call)
                    pending.pop(0)
                    self.emit("result", "ok" if result.ok else result.content[:100])
                    messages.append({"role": "tool", "tool_call_id": call.id,
                                     "content": result.content})
            else:
                self.emit("error", f"stopped after {self.max_steps} steps")
        except KeyboardInterrupt:
            for call in pending:
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": "ERROR: interrupted by user"})
            outcome = "interrupted"
        except Exception:  # noqa: BLE001
            self.emit("error", "internal error")
            outcome = "internal_error"
        return TaskResult(outcome, final_text, steps)

    @staticmethod
    def _assistant_message(resp) -> dict:
        msg: dict = {"role": "assistant", "content": resp.text}
        if resp.tool_calls:
            msg["tool_calls"] = [{
                "id": tc.id, "type": "function",
                "function": {"name": tc.name,
                             "arguments": "{}" if "__parse_error" in tc.arguments else tc.raw_arguments},
            } for tc in resp.tool_calls]
        return msg

    def _execute(self, call) -> ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(False, f"ERROR: unknown tool {call.name}. Available: {', '.join(self.tools)}")
        if "__parse_error" in call.arguments:
            return ToolResult(False, "ERROR: bad arguments: arguments were not a valid JSON object")
        problem = validate_args(tool.schema, call.arguments)
        if problem:
            return ToolResult(False, f"ERROR: bad arguments: {problem}")
        self.emit("tool", f"-> {call.name} {call.arguments.get('path', '')}".rstrip())
        try:
            return tool.run(call.arguments, self.ctx)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(False, f"ERROR: {type(exc).__name__}: {exc}")
