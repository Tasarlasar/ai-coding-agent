"""Settings (global + workspace scope), credentials and remembered state."""
from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

CATEGORIES = ("read", "write", "edit", "shell")
MODES = ("allow", "ask", "deny")
_STRICTNESS = {"deny": 0, "ask": 1, "allow": 2}

DEFAULTS: dict[str, Any] = {
    "model": None,
    "api_base": None,
    "permissions": {"read": "allow", "write": "ask", "edit": "ask", "shell": "ask"},
    "max_steps": 25,
    "shell_timeout_s": 60,
    "output_limit_chars": 8000,
    "context_budget_tokens": 60000,
}
GLOBAL_ONLY = ("model", "api_base")
WORKSPACE_KEYS = ("max_steps", "shell_timeout_s", "output_limit_chars", "context_budget_tokens")
UNSET = object()


class ConfigError(Exception):
    """Raised when a setting cannot be saved or is invalid."""
    pass


@dataclass(frozen=True)
class Settings:
    """Effective settings for one run, after merging defaults, global, workspace and flags."""
    model: str | None
    api_base: str | None
    permissions: Mapping[str, str]
    max_steps: int
    shell_timeout_s: float
    output_limit_chars: int
    context_budget_tokens: int


@dataclass(frozen=True)
class LoadedSettings:
    """Settings plus where each value came from, warnings and loosened permissions."""
    settings: Settings
    sources: Mapping[str, str]
    warnings: tuple[str, ...]
    # category -> mode it would have without the workspace file (only where the workspace loosens it)
    loosened: Mapping[str, str] = field(default_factory=dict)


# ---- paths -----------------------------------------------------------------

def global_dir() -> Path:
    """Return the global config directory."""
    override = os.environ.get("AGENT_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "agent-cli"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "agent-cli"


def global_config_path() -> Path:
    """Return the path of the global config file."""
    return global_dir() / "config.json"


def credentials_path() -> Path:
    """Return the path of the credentials file."""
    return global_dir() / "credentials.json"


def workspace_config_path(workspace: Path) -> Path:
    """Return the path of the per-workspace config file."""
    return Path(workspace) / ".agent" / "config.json"


def _scope_path(scope: str, workspace: Path | None) -> Path:
    if scope == "global":
        return global_config_path()
    if scope == "workspace":
        if workspace is None:
            raise ConfigError("no workspace selected")
        return workspace_config_path(workspace)
    raise ConfigError(f"unknown scope: {scope}")


# ---- validation ------------------------------------------------------------

def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


_VALIDATORS = {
    "model": lambda v: isinstance(v, str) and bool(v.strip()),
    "api_base": lambda v: v is None or (isinstance(v, str) and bool(v.strip())),
    "max_steps": lambda v: _is_int(v) and 1 <= v <= 200,
    "shell_timeout_s": lambda v: _is_num(v) and 1 <= v <= 600,
    "output_limit_chars": lambda v: _is_int(v) and 500 <= v <= 100000,
    "context_budget_tokens": lambda v: _is_int(v) and 2000 <= v <= 2_000_000,
}


def _read_json(path: Path) -> tuple[dict | None, list[str]]:
    """Return (data, warnings). Missing file -> (None, []). Corrupt -> (None, [warning])."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, []
    except OSError as exc:
        return None, [f"config {path} invalid: {exc.strerror or exc}; using defaults"]
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, [f"config {path} invalid: {exc}; using defaults"]
    if not isinstance(data, dict):
        return None, [f"config {path} invalid: not a JSON object; using defaults"]
    return data, []


def _clean(data: dict, scope: str, path: Path, warnings: list[str]) -> dict:
    """Validate one file's content, returning only valid, allowed keys."""
    out: dict[str, Any] = {}
    for key, validate in _VALIDATORS.items():
        if key not in data:
            continue
        if scope == "workspace" and key in GLOBAL_ONLY:
            warnings.append(f"workspace config key '{key}' is not allowed (global only)")
            continue
        if not validate(data[key]):
            warnings.append(f"config {path}: invalid value for '{key}'; ignored")
            continue
        out[key] = data[key]
    if scope == "workspace" and "api_key" in data:
        warnings.append("workspace config key 'api_key' is not allowed (global only)")
    if "permissions" in data:
        block = data["permissions"]
        if not isinstance(block, dict):
            warnings.append(f"config {path}: 'permissions' must be an object; ignored")
        else:
            perms = {}
            for cat, mode in block.items():
                if cat not in CATEGORIES or mode not in MODES:
                    warnings.append(f"config {path}: invalid permission '{cat}'; ignored")
                else:
                    perms[cat] = mode
            out["permissions"] = perms
    return out


# ---- load ------------------------------------------------------------------

def load_settings(workspace: Path | None, overrides: Mapping[str, Any] | None = None) -> LoadedSettings:
    """Merge defaults, global config, workspace config and overrides into LoadedSettings."""
    warnings: list[str] = []
    gpath = global_config_path()
    gdata, w = _read_json(gpath)
    warnings += w
    g = _clean(gdata, "global", gpath, warnings) if gdata is not None else {}
    wdata, wpath = None, None
    if workspace is not None:
        wpath = workspace_config_path(workspace)
        wdata, w = _read_json(wpath)
        warnings += w
    ws = _clean(wdata, "workspace", wpath, warnings) if wdata is not None else {}

    values: dict[str, Any] = {k: v for k, v in DEFAULTS.items() if k != "permissions"}
    sources: dict[str, str] = {k: "default" for k in values}
    for scope, layer in (("global", g), ("workspace", ws)):
        for key, val in layer.items():
            if key != "permissions":
                values[key], sources[key] = val, scope

    perms = dict(DEFAULTS["permissions"])
    psrc = {c: "default" for c in CATEGORIES}
    base_perms = dict(perms)  # effective without the workspace layer
    for scope, layer in (("global", g), ("workspace", ws)):
        for cat, mode in layer.get("permissions", {}).items():
            perms[cat], psrc[cat] = mode, scope
            if scope == "global":
                base_perms[cat] = mode
    loosened: dict[str, str] = {}
    for cat, mode in ws.get("permissions", {}).items():
        if _STRICTNESS[mode] > _STRICTNESS[base_perms[cat]]:
            origin = "global" if cat in g.get("permissions", {}) else "default"
            warnings.append(f"workspace config sets {cat}={mode} ({origin}: {base_perms[cat]})")
            loosened[cat] = base_perms[cat]

    for key, val in (overrides or {}).items():
        if key == "permissions":
            for cat, mode in val.items():
                perms[cat], psrc[cat] = mode, "session"
        elif val is not None and key in _VALIDATORS and _VALIDATORS[key](val):
            values[key], sources[key] = val, "flag"

    for cat in CATEGORIES:
        sources[f"permissions.{cat}"] = psrc[cat]
    settings = Settings(permissions=MappingProxyType(perms), **values)
    return LoadedSettings(settings, MappingProxyType(sources), tuple(warnings), MappingProxyType(loosened))


def loosened_categories(loaded: LoadedSettings) -> list[str]:
    """List the categories where the workspace config is less strict than the global mode."""
    return [c for c in CATEGORIES if c in loaded.loosened]


def overrides_without_loosening(loaded: LoadedSettings) -> dict:
    """Overrides that restore the non-workspace mode of each loosened category."""
    return {"permissions": dict(loaded.loosened)} if loaded.loosened else {}


# ---- save ------------------------------------------------------------------

def _atomic_write(path: Path, text: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if mode is None:
        tmp.write_text(text, encoding="utf-8")
    else:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def save_setting(scope: str, key_path: str, value: Any, workspace: Path | None) -> None:
    """Save one setting to the global or workspace file; pass UNSET to remove it."""
    parts = key_path.split(".")
    top = parts[0]
    if scope == "workspace" and top in GLOBAL_ONLY:
        raise ConfigError(f"'{top}' can only be saved to global scope")
    path = _scope_path(scope, workspace)
    if top == "permissions":
        if len(parts) != 2 or parts[1] not in CATEGORIES:
            raise ConfigError(f"unknown setting: {key_path}")
        if value is not UNSET and value not in MODES:
            raise ConfigError(f"invalid mode: {value}")
    elif len(parts) != 1 or top not in _VALIDATORS:
        raise ConfigError(f"unknown setting: {key_path}")
    elif value is not UNSET and not _VALIDATORS[top](value):
        raise ConfigError(f"invalid value for {top}")
    data, warns = _read_json(path)
    if warns:
        raise ConfigError(f"refusing to overwrite {path}: file is corrupt; fix or delete it")
    data = data or {}
    if top == "permissions":
        block = data.get("permissions")
        block = dict(block) if isinstance(block, dict) else {}
        if value is UNSET:
            block.pop(parts[1], None)
        else:
            block[parts[1]] = value
        if block:
            data["permissions"] = block
        else:
            data.pop("permissions", None)
    elif value is UNSET:
        data.pop(top, None)
    else:
        data[top] = value
    data["version"] = 1
    _atomic_write(path, json.dumps(data, indent=2) + "\n")


# ---- credentials -----------------------------------------------------------

def resolve_api_key(env: Mapping[str, str]) -> str | None:
    """Return the API key from AGENT_API_KEY or the credentials file, else None."""
    key = (env.get("AGENT_API_KEY") or "").strip()
    if key:
        return key
    data, _ = _read_json(credentials_path())
    value = (data or {}).get("api_key")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def save_api_key(key: str) -> None:
    """Store the API key in the credentials file with mode 0600."""
    key = key.strip()
    if not key:
        raise ConfigError("empty API key")
    _atomic_write(credentials_path(), json.dumps({"version": 1, "api_key": key}) + "\n", 0o600)


def credentials_warning() -> str | None:
    """Return a warning if the credentials file permissions are too open, else None."""
    if sys.platform == "win32":
        return None
    path = credentials_path()
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return None
    if mode & 0o077:
        return f"credentials file permissions too open; run chmod 600 {path}"
    return None


# ---- remembered state ------------------------------------------------------

def load_state() -> dict:
    """Load remembered state such as the last workspace."""
    data, _ = _read_json(global_dir() / "state.json")
    return data or {}


def save_last_workspace(path: str) -> None:
    """Remember the last used workspace path."""
    state = load_state()
    state["last_workspace"] = path
    _atomic_write(global_dir() / "state.json", json.dumps(state))
