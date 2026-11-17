"""Compact, runtime-written change log. No model calls, no diffs, no shell command text."""
from __future__ import annotations

import re
from datetime import datetime

from agent.workspace import Workspace

NO_REASON = "(none given)"
MAX_REASON = 200
MAX_REQUEST = 80
MAX_FILES = 8
MAX_VERIFY = 4
SUMMARY_CAP = 1500


def _field(text: str) -> str:
    """One-line, pipe-free field."""
    return re.sub(r"[|\r\n]+", " ", text)


def _reason(reason: str | None) -> str:
    cleaned = " ".join(_field(reason or "").split())[:MAX_REASON]
    return cleaned or NO_REASON


class ChangeLog:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.path = workspace.root / ".agent" / "changelog.log"
        self.error: str | None = None
        self._task_id: str | None = None
        self._last_base: str | None = None
        self._dupes = 0
        self._changes: list[tuple[str, str, str]] = []
        self._verifications: list[tuple[str, int]] = []

    # ---- writing ----
    def _append(self, line: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            self.error = self.error or f"change log not written: {exc.strerror or exc}"

    def pop_error(self) -> str | None:
        err, self.error = self.error, None
        return err

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def begin_task(self, request: str) -> None:
        base = self._now()
        if base == self._last_base:
            self._dupes += 1
            task_id = f"{base}#{self._dupes + 1}"
        else:
            self._last_base, self._dupes, task_id = base, 0, base
        self._task_id = task_id
        self._changes, self._verifications = [], []
        self._append(f"# task {task_id} | {' '.join(_field(request).split())[:MAX_REQUEST]}")

    def record(self, action: str, target: str, reason: str | None) -> None:
        action, target, reason = _field(action), _field(target), _reason(reason)
        self._changes.append((action, target, reason))
        self._append(f"{self._now()} | {action} | {target} | {reason}")

    def record_verification(self, command: str, exit_code: int) -> None:
        """In memory only. The command text never reaches the file."""
        self._verifications.append((command, exit_code))

    def end_task(self, final_text: str | None, outcome: str) -> list[str]:
        task_id = self._task_id or self._now()
        files: dict[str, str] = {}
        for _, target, reason in self._changes:
            files.pop(target, None)
            files[target] = reason
        shown = list(files.items())[:MAX_FILES]
        header = f"Task {outcome}: {len(self._changes)} change(s)"
        file_lines = [f"  {t}: {r}" for t, r in shown]
        if len(files) > MAX_FILES:
            file_lines.append(f"  +{len(files) - MAX_FILES} more")
        terminal = [header, *file_lines]
        for command, code in self._verifications[-MAX_VERIFY:]:
            cmd = " ".join(command.split())
            terminal.append(f"  verify: {cmd[:80]} -> exit {code}")
        log_lines = [header, *file_lines]
        if self._verifications:
            n = len(self._verifications)
            log_lines.append(f"verify: {n} shell run(s), last exit {self._verifications[-1][1]}")
        for line in log_lines:
            self._append(f"#> {_field(line)}")
        self._append(f"# end {task_id} {_field(outcome)} | {len(self._changes)} changes")
        return terminal

    # ---- reading ----
    def _recent_tasks(self, count: int = 3) -> list[str]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        started: dict[str, str] = {}
        order: list[str] = []
        ended: dict[str, str] = {}
        for line in lines:
            if line.startswith("# task "):
                task_id, _, request = line[len("# task "):].partition(" | ")
                started[task_id] = request
                order.append(task_id)
            elif line.startswith("# end "):
                parts = line[len("# end "):].partition(" | ")[0].split(" ")
                if len(parts) >= 2:
                    ended[parts[0]] = parts[1]
        return [f"{started[t]} ({ended.get(t, 'unfinished')})" for t in order[-count:]]

    def project_summary(self) -> str:
        entries = self.workspace.top_entries()
        parts = [f"Workspace: {self.workspace.root.name}",
                 "Top-level: " + (", ".join(entries) if entries else "(empty)")]
        tasks = self._recent_tasks()
        if tasks:
            parts.append("Recent tasks:\n" + "\n".join(f"- {t}" for t in tasks))
        return "\n".join(parts)[:SUMMARY_CAP]
