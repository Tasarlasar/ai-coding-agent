"""The agent loop: model call, tool calls, results, repeat."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from agent.prompts import SYSTEM_PROMPT
from agent.providers import Provider, ProviderError
from agent.changelog import ChangeLog
from agent.config import Settings
from agent.context import ContextManager
from agent.permissions import PermissionGate
from agent.workspace import Workspace, WorkspaceError
from agent.tools import Tool, ToolContext, ToolResult, validate_args


@dataclass
class TaskResult:
    outcome: str  # done | step_limit | provider_error | interrupted | internal_error
    final_text: str | None
    steps: int


class AgentLoop:
    def __init__(self, provider: Provider, tools: dict[str, Tool], workspace: Workspace,
                 settings: Settings, gate: PermissionGate, context: ContextManager,
                 changelog: ChangeLog, emit: Callable[[str, str], None]):
        self.provider = provider
        self.tools = tools
        self.workspace = workspace
        self.ctx = ToolContext(workspace, settings)
        self.max_steps = settings.max_steps
        self.gate = gate
        self.context = context
        self.changelog = changelog
        self._log_warned = False
        self.emit = emit
        self.schemas = [t.schema for t in tools.values()]

    def run_task(self, request: str) -> TaskResult:
        summary = self.changelog.project_summary()  # before begin_task, so it excludes this task
        self.changelog.begin_task(request)
        messages = self.context.start_task(SYSTEM_PROMPT, summary, request)
        outcome, final_text, steps = "step_limit", None, 0
        pending: list = []
        try:
            for steps in range(1, self.max_steps + 1):
                messages = self.context.prepare(messages)
                try:
                    resp = self.provider.complete(messages, self.schemas)
                except ProviderError as exc:
                    self.emit("error", str(exc))
                    outcome = "provider_error"
                    break
                self.context.note_usage(resp.usage_total_tokens)
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
                    self.context.add_tool_result(messages, call.id, result.content)
            else:
                self.emit("error", f"stopped after {self.max_steps} steps")
        except KeyboardInterrupt:
            for call in pending:
                self.context.add_tool_result(messages, call.id, "ERROR: interrupted by user")
            outcome = "interrupted"
        except Exception:  # noqa: BLE001
            self.emit("error", "internal error")
            outcome = "internal_error"
        finally:
            for line in self.changelog.end_task(final_text, outcome):
                self.emit("info", line)
            self._warn_log_error()
        return TaskResult(outcome, final_text, steps)

    def _warn_log_error(self) -> None:
        error = self.changelog.pop_error()
        if error and not self._log_warned:
            self._log_warned = True
            self.emit("warning", error)

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

    def _display_target(self, args: dict) -> str:
        path = args.get("path")
        if isinstance(path, str) and path:
            try:
                return self.workspace.rel(self.workspace.resolve(path))
            except WorkspaceError:
                return path
        return str(args.get("command", ""))[:60]

    def _execute(self, call) -> ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(False, f"ERROR: unknown tool {call.name}. Available: {', '.join(self.tools)}")
        if "__parse_error" in call.arguments:
            return ToolResult(False, "ERROR: bad arguments: arguments were not a valid JSON object")
        problem = validate_args(tool.schema, call.arguments)
        if problem:
            return ToolResult(False, f"ERROR: bad arguments: {problem}")
        target = self._display_target(call.arguments)
        self.emit("tool", f"-> {call.name} {target}".rstrip())
        allowed, message = self.gate.check(tool, call.arguments)
        if not allowed:
            return ToolResult(False, message)
        try:
            result = tool.run(call.arguments, self.ctx)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(False, f"ERROR: {type(exc).__name__}: {exc}")
        self._log(tool, call.arguments, result)
        return result

    def _log(self, tool: Tool, args: dict, result: ToolResult) -> None:
        """Feed the change log. Only successful write/edit calls are logged; shell text never is."""
        if tool.category in ("write", "edit") and result.ok:
            rel = self.workspace.rel(self.workspace.resolve(args["path"]))
            self.changelog.record(tool.category, rel, args.get("reason"))
        elif tool.category == "shell":
            match = re.match(r"exit_code: (-?\d+)", result.content)
            self.changelog.record_verification(str(args.get("command", "")),
                                               int(match.group(1)) if match and result.ok else -1)
        self._warn_log_error()
