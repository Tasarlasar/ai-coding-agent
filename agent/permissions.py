"""Permission modes and the gate every tool call passes through."""
from __future__ import annotations

from typing import Callable

from agent.config import CATEGORIES, Settings
from agent.tools import Tool
from agent.workspace import Workspace, WorkspaceError

__all__ = ["CATEGORIES", "resolve_mode", "PermissionGate"]

_PATH_TOOLS = {"read_file", "write_file", "edit_file", "list_dir", "search"}


def resolve_mode(category: str, settings: Settings) -> str:
    return settings.permissions.get(category, "ask")


class PermissionGate:
    def __init__(self, settings: Settings, confirm: Callable[[str], str],
                 session_allow: set[str], workspace: Workspace):
        self.settings = settings
        self.confirm = confirm
        self.session_allow = session_allow
        self.workspace = workspace

    def check(self, tool: Tool, args: dict) -> tuple[bool, str]:
        shown = ""
        verb = tool.name
        if tool.name in _PATH_TOOLS:
            raw = args.get("path", ".")
            try:
                real = self.workspace.resolve(raw)
            except WorkspaceError:
                return False, f"ERROR: path escapes workspace: {raw}"
            shown = self.workspace.rel(real)
            if tool.name == "write_file":
                verb = "overwrite" if real.exists() else "write"
                verb = f"{tool.name} ({verb})"
        else:
            shown = str(args.get("command", ""))[:200]
        mode = resolve_mode(tool.category, self.settings)
        if mode == "deny":
            return False, f"ERROR: {tool.name} is denied by permission settings"
        if mode == "allow" or tool.category in self.session_allow:
            return True, ""
        reason = args.get("reason")
        prompt = f"{verb}: {shown}" + (f"  ({reason[:200]})" if isinstance(reason, str) and reason else "")
        try:
            answer = self.confirm(prompt)
        except EOFError:
            answer = "no"
        if answer == "always":
            self.session_allow.add(tool.category)
            return True, ""
        if answer == "yes":
            return True, ""
        return False, f"ERROR: user declined {tool.name}"
