"""Tool registry, schemas and implementations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

MAX_FILE_BYTES = 1_000_000


@dataclass
class ToolResult:
    ok: bool
    content: str


@dataclass
class ToolContext:
    workspace_root: Path
    settings: Any = None


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


def _read_file(args: dict, ctx: ToolContext) -> ToolResult:
    path = ctx.workspace_root / args["path"]
    if not path.is_file():
        return _err(f"not a file: {args['path']}")
    start, end = args.get("start_line"), args.get("end_line")
    if start is not None and start < 1 or end is not None and end < 1:
        return _err("start_line and end_line must be >= 1")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES and start is None and end is None:
        return _err(f"file is {size} bytes; pass start_line/end_line to read a range")
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return _err(f"binary file refused: {args['path']}")
    if start is not None and end is not None and start > end:
        return _err("start_line is greater than end_line")
    lines = data.decode("utf-8", errors="replace").splitlines()
    first = start or 1
    last = min(end if end is not None else len(lines), len(lines))
    out = [f"{n}\t{lines[n - 1]}" for n in range(first, last + 1)]
    return ToolResult(True, "\n".join(out))


def _path_prop(desc: str = "File path relative to the workspace") -> dict:
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
    ]
    return {t.name: t for t in tools}
