"""Tool registry, schemas and implementations."""
from __future__ import annotations

import fnmatch
import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent import secrets

MAX_FILE_BYTES = 1_000_000
MAX_REASON = 200
SKIP_DIRS = {".git", ".agent", ".venv", "node_modules"}


@dataclass
class ToolResult:
    ok: bool
    content: str


@dataclass
class ToolContext:
    workspace_root: Path
    settings: Any = None

    def setting(self, name: str, default):
        return getattr(self.settings, name, default)


@dataclass
class Tool:
    name: str
    category: str
    schema: dict
    run: Callable[[dict, ToolContext], ToolResult]


def _err(msg: str) -> ToolResult:
    return ToolResult(False, f"ERROR: {msg}")


_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool}


def validate_args(schema: dict, args: dict) -> str | None:
    """Tiny validator: required keys and primitive types only."""
    params = schema["function"]["parameters"]
    for key in params.get("required", []):
        if key not in args:
            return f"missing required argument '{key}'"
    for key, value in args.items():
        spec = params.get("properties", {}).get(key)
        if not spec or "type" not in spec:
            continue
        expected = _TYPES[spec["type"]]
        if isinstance(value, bool) and spec["type"] != "boolean":
            return f"argument '{key}' must be {spec['type']}"
        if not isinstance(value, expected):
            return f"argument '{key}' must be {spec['type']}"
    return None


def _resolve_in_root(root: Path, p: str) -> Path:
    """Interim resolver (slice 3 replaces it with Workspace.resolve)."""
    return Path(os.path.realpath(root / p))


def is_agent_dir_path(root: Path, real: Path) -> bool:
    agent_dir = root / ".agent"

    def norm(x: Path) -> str:
        n = os.path.normcase(str(x))
        return n.lower() if sys.platform in ("darwin", "win32") else n

    r, a = norm(real), norm(agent_dir)
    if r == a or r.startswith(a + os.sep):
        return True
    if agent_dir.exists():
        for anc in [real, *real.parents]:
            try:
                if anc.exists() and os.path.samefile(anc, agent_dir):
                    return True
            except OSError:
                continue
    return False


def _head_tail(text: str, limit: int) -> str:
    """Interim truncation (slice 5 replaces it with context.truncate_output)."""
    if len(text) <= limit:
        return text
    h = int(limit * 0.6)
    return f"{text[:h]}\n... [omitted {len(text) - limit} chars of {len(text)} total] ...\n{text[len(text) - (limit - h):]}"


def _read_file(args: dict, ctx: ToolContext) -> ToolResult:
    path = _resolve_in_root(ctx.workspace_root, args["path"])
    if not path.is_file():
        return _err(f"not a file: {args['path']}")
    start, end = args.get("start_line"), args.get("end_line")
    if (start is not None and start < 1) or (end is not None and end < 1):
        return _err("start_line and end_line must be >= 1")
    if start is not None and end is not None and start > end:
        return _err("start_line is greater than end_line")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES and start is None and end is None:
        return _err(f"file is {size} bytes; pass start_line/end_line to read a range")
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return _err(f"binary file refused: {args['path']}")
    lines = data.decode("utf-8", errors="replace").splitlines()
    first = start or 1
    last = min(end if end is not None else len(lines), len(lines))
    out = "\n".join(f"{n}\t{lines[n - 1]}" for n in range(first, last + 1))
    limit = ctx.setting("output_limit_chars", 8000)
    if len(out) > limit:
        out = _head_tail(out, limit) + "\nuse start_line/end_line to read the omitted part"
    return ToolResult(True, out)


def _cap_reason(args: dict) -> str | None:
    reason = args.get("reason")
    return reason[:MAX_REASON] if isinstance(reason, str) else None


def _write_file(args: dict, ctx: ToolContext) -> ToolResult:
    root = ctx.workspace_root
    path = _resolve_in_root(root, args["path"])
    if is_agent_dir_path(root, path):
        return _err("paths under .agent/ are reserved for the agent runtime")
    if path.is_dir():
        return _err(f"is a directory: {args['path']}")
    content = args["content"]
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        return _err("content exceeds 1 MB")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return ToolResult(True, f"wrote {len(content)} chars to {args['path']}")


def _edit_file(args: dict, ctx: ToolContext) -> ToolResult:
    root = ctx.workspace_root
    path = _resolve_in_root(root, args["path"])
    if is_agent_dir_path(root, path):
        return _err("paths under .agent/ are reserved for the agent runtime")
    old, new = args["old_text"], args["new_text"]
    if not old:
        return _err("old_text must not be empty")
    if not path.is_file():
        return _err(f"file not found: {args['path']}")
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        text = f.read()
    count = text.count(old)
    if count == 0:
        return _err(f"old_text not found in {args['path']}. Re-read the file and copy the text exactly.")
    if count > 1:
        return _err(f"old_text matches {count} times in {args['path']}. "
                    "Include more surrounding lines to make it unique.")
    updated = text.replace(old, new, 1)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(updated)
    return ToolResult(True, f"edited {args['path']}")


def _list_dir(args: dict, ctx: ToolContext) -> ToolResult:
    root = ctx.workspace_root
    path = _resolve_in_root(root, args.get("path", "."))
    if not path.is_dir():
        return _err(f"not a directory: {args.get('path', '.')}")
    entries = []
    for child in sorted(path.iterdir(), key=lambda c: c.name):
        if child.name == ".agent" and path == root:
            continue
        entries.append(child.name + ("/" if child.is_dir() else ""))
    shown = entries[:200]
    if len(entries) > 200:
        shown.append(f"... {len(entries) - 200} more")
    return ToolResult(True, "\n".join(shown) if shown else "(empty)")


def _search(args: dict, ctx: ToolContext) -> ToolResult:
    root = ctx.workspace_root
    try:
        regex = re.compile(args["pattern"])
    except re.error as exc:
        return _err(f"invalid regex: {exc}")
    start = _resolve_in_root(root, args.get("path", "."))
    glob = args.get("glob")
    if start.is_file():
        candidates = [start]
    elif start.is_dir():
        def walk():
            for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
                dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
                for name in sorted(filenames):
                    yield Path(dirpath) / name
        candidates = walk()
    else:
        return _err(f"path not found: {args.get('path', '.')}")
    matches: list[str] = []
    for file in candidates:
        try:
            real = _resolve_in_root(root, str(file))
            if not (real == root or root in real.parents):
                continue
        except OSError:
            continue
        rel = file.relative_to(root).as_posix() if root in file.parents else file.name
        if glob and not fnmatch.fnmatch(rel, glob):
            continue
        try:
            if real.stat().st_size > MAX_FILE_BYTES:
                continue
            data = real.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        for n, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            if regex.search(line):
                matches.append(f"{rel}:{n}: {line[:200]}")
                if len(matches) >= 100:
                    return ToolResult(True, "\n".join(matches) + "\n(stopped at 100 matches)")
    return ToolResult(True, "\n".join(matches) if matches else "no matches")


def _run_shell(args: dict, ctx: ToolContext) -> ToolResult:
    cap = ctx.setting("shell_timeout_s", 60)
    timeout = min(args.get("timeout", cap), cap)
    limit = ctx.setting("output_limit_chars", 8000)
    env = {k: v for k, v in os.environ.items() if not secrets.secret_name(k)}
    posix = sys.platform != "win32"
    proc = subprocess.Popen(
        args["command"], shell=True, cwd=ctx.workspace_root, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",
        env=env, start_new_session=posix)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if posix:
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            pass
        out, err = proc.communicate()
        return ToolResult(False, f"ERROR: command timed out after {timeout}s\n"
                          f"stdout:\n{_head_tail(out or '', limit)}\nstderr:\n{_head_tail(err or '', limit)}")
    return ToolResult(True, f"exit_code: {proc.returncode}\nstdout:\n{_head_tail(out or '', limit)}"
                      f"\nstderr:\n{_head_tail(err or '', limit)}")


_REASON = {"type": "string", "description": "one short sentence: why this change"}


def _path_prop(desc: str = "Path relative to the workspace") -> dict:
    return {"type": "string", "description": desc}


def _schema(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required}}}


def build_tools() -> dict[str, Tool]:
    tools = [
        Tool("read_file", "read", _schema(
            "read_file", "Read a text file. Output lines are prefixed with 'N<TAB>' (not part of the file).",
            {"path": _path_prop(),
             "start_line": {"type": "integer", "description": "First line (1-based)"},
             "end_line": {"type": "integer", "description": "Last line (inclusive)"}},
            ["path"]), _read_file),
        Tool("write_file", "write", _schema(
            "write_file", "Create or overwrite a file (parent directories are created).",
            {"path": _path_prop(), "content": {"type": "string", "description": "Full file content"},
             "reason": _REASON}, ["path", "content"]), _write_file),
        Tool("edit_file", "edit", _schema(
            "edit_file", "Replace one exact, unique occurrence of old_text with new_text.",
            {"path": _path_prop(), "old_text": {"type": "string", "description": "Exact text to replace"},
             "new_text": {"type": "string", "description": "Replacement text"},
             "reason": _REASON}, ["path", "old_text", "new_text"]), _edit_file),
        Tool("list_dir", "read", _schema(
            "list_dir", "List a directory (non-recursive). Directories end with '/'.",
            {"path": _path_prop("Directory, default '.'")}, []), _list_dir),
        Tool("search", "read", _schema(
            "search", "Regex search in files. Returns path:line: text.",
            {"pattern": {"type": "string", "description": "Python regular expression"},
             "path": _path_prop("File or directory, default '.'"),
             "glob": {"type": "string", "description": "Filter on relative path, e.g. *.py"}},
            ["pattern"]), _search),
        Tool("run_shell", "shell", _schema(
            "run_shell", "Run a shell command in the workspace directory.",
            {"command": {"type": "string", "description": "Command line"}, "reason": _REASON,
             "timeout": {"type": "integer", "description": "Timeout in seconds"}},
            ["command"]), _run_shell),
    ]
    return {t.name: t for t in tools}
