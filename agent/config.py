"""Config locations and remembered state (settings arrive in a later slice)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def global_dir() -> Path:
    override = os.environ.get("AGENT_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "agent-cli"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "agent-cli"


def load_state() -> dict:
    try:
        data = json.loads((global_dir() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_last_workspace(path: str) -> None:
    d = global_dir()
    d.mkdir(parents=True, exist_ok=True)
    state = load_state()
    state["last_workspace"] = path
    tmp = d / "state.json.tmp"
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, d / "state.json")
