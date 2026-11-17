import json
import os
import stat
import sys

import pytest

from agent import config
from agent.config import UNSET, ConfigError, load_settings, save_setting


@pytest.fixture
def ws(tmp_path):
    d = tmp_path / "ws"
    d.mkdir()
    return d


def write_ws(ws, data):
    (ws / ".agent").mkdir(exist_ok=True)
    (ws / ".agent" / "config.json").write_text(data if isinstance(data, str) else json.dumps(data))


def write_global(data):
    d = config.global_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(data if isinstance(data, str) else json.dumps(data))


def test_defaults(ws):
    loaded = load_settings(ws)
    assert dict(loaded.settings.permissions) == {"read": "allow", "write": "ask", "edit": "ask", "shell": "ask"}
    assert loaded.settings.max_steps == 25 and loaded.settings.shell_timeout_s == 60
    assert loaded.sources["permissions.shell"] == "default" and not loaded.warnings


def test_precedence_per_category(ws):
    write_global({"permissions": {"shell": "deny", "write": "allow"}, "max_steps": 10})
    write_ws(ws, {"permissions": {"shell": "ask"}, "max_steps": 5})
    s = load_settings(ws)
    assert s.settings.permissions["shell"] == "ask" and s.sources["permissions.shell"] == "workspace"
    assert s.settings.permissions["write"] == "allow" and s.sources["permissions.write"] == "global"
    assert s.settings.max_steps == 5 and s.sources["max_steps"] == "workspace"
    assert s.settings.permissions["edit"] == "ask" and s.sources["permissions.edit"] == "default"


def test_workspace_override_does_not_affect_other_workspace(tmp_path, ws):
    other = tmp_path / "other"
    other.mkdir()
    write_global({"permissions": {"shell": "ask"}})
    write_ws(ws, {"permissions": {"shell": "allow"}})
    assert load_settings(ws).settings.permissions["shell"] == "allow"
    assert load_settings(other).settings.permissions["shell"] == "ask"


def test_persistence_round_trip(ws):
    save_setting("global", "permissions.write", "allow", ws)
    save_setting("workspace", "permissions.shell", "deny", ws)
    save_setting("global", "model", "gpt-4o", ws)
    save_setting("workspace", "max_steps", 7, ws)
    s = load_settings(ws)
    assert s.settings.permissions["write"] == "allow" and s.settings.permissions["shell"] == "deny"
    assert s.settings.model == "gpt-4o" and s.settings.max_steps == 7
    assert (config.global_dir() / "config.json").exists()
    assert (ws / ".agent" / "config.json").exists()
    assert not list(config.global_dir().glob("*.tmp"))


def test_corrupt_file_falls_back_and_is_not_overwritten(ws):
    write_ws(ws, "{not json")
    s = load_settings(ws)
    assert any("invalid" in w for w in s.warnings)
    assert [s.settings.permissions[c] for c in config.CATEGORIES] == ["allow", "ask", "ask", "ask"]
    with pytest.raises(ConfigError):
        save_setting("workspace", "permissions.shell", "allow", ws)
    assert (ws / ".agent" / "config.json").read_text() == "{not json"


def test_corrupt_global_never_falls_to_allow(ws):
    write_global("[1, 2]")
    s = load_settings(ws)
    assert s.warnings and s.settings.permissions["write"] == "ask"


def test_invalid_fields_ignored_with_warning(ws):
    write_global({"max_steps": 0, "shell_timeout_s": "x", "output_limit_chars": 5,
                  "context_budget_tokens": 1, "model": "", "permissions": {"shell": "yes", "bogus": "allow",
                                                                           "write": "allow"}})
    s = load_settings(ws)
    assert s.settings.max_steps == 25 and s.settings.model is None
    assert s.settings.permissions["shell"] == "ask" and s.settings.permissions["write"] == "allow"
    assert len(s.warnings) >= 6


def test_invalid_permissions_block_falls_back_to_lower_scope(ws):
    write_global({"permissions": {"shell": "deny"}})
    write_ws(ws, {"permissions": "allow"})
    s = load_settings(ws)
    assert s.settings.permissions["shell"] == "deny" and s.sources["permissions.shell"] == "global"
    write_global({"permissions": ["x"]})
    assert load_settings(ws).settings.permissions["shell"] == "ask"


def test_workspace_cannot_set_global_only_keys(ws):
    write_ws(ws, {"model": "evil", "api_base": "http://evil", "api_key": "k", "max_steps": 3})
    s = load_settings(ws)
    assert s.settings.model is None and s.settings.api_base is None and s.settings.max_steps == 3
    for key in ("model", "api_base", "api_key"):
        assert f"workspace config key '{key}' is not allowed (global only)" in s.warnings
    with pytest.raises(ConfigError):
        save_setting("workspace", "model", "x", ws)


def test_loosening_warning_and_overrides(ws):
    write_global({"permissions": {"write": "deny"}})
    write_ws(ws, {"permissions": {"shell": "allow", "write": "ask", "edit": "deny"}})
    s = load_settings(ws)
    assert "workspace config sets shell=allow (default: ask)" in s.warnings
    assert "workspace config sets write=ask (global: deny)" in s.warnings
    assert config.loosened_categories(s) == ["write", "shell"]
    restored = load_settings(ws, config.overrides_without_loosening(s)).settings.permissions
    assert restored["shell"] == "ask" and restored["write"] == "deny" and restored["edit"] == "deny"


def test_unset_removes_key_and_empty_permissions(ws):
    save_setting("workspace", "permissions.shell", "allow", ws)
    save_setting("workspace", "max_steps", 4, ws)
    save_setting("workspace", "permissions.shell", UNSET, ws)
    data = json.loads((ws / ".agent" / "config.json").read_text())
    assert "permissions" not in data and data["max_steps"] == 4
    save_setting("workspace", "max_steps", UNSET, ws)
    assert "max_steps" not in json.loads((ws / ".agent" / "config.json").read_text())


def test_save_rejects_bad_input(ws):
    for key, value in (("permissions.shell", "maybe"), ("permissions.net", "allow"),
                       ("max_steps", 0), ("nope", 1)):
        with pytest.raises(ConfigError):
            save_setting("global", key, value, ws)


def test_cli_flag_overrides_not_persisted(ws):
    s = load_settings(ws, {"model": "m1", "max_steps": 3})
    assert s.settings.model == "m1" and s.sources["model"] == "flag"
    assert not (config.global_dir() / "config.json").exists()


# credentials
def test_api_key_env_beats_file_and_blank_is_unset():
    config.save_api_key("file-key-123456")
    assert config.resolve_api_key({}) == "file-key-123456"
    assert config.resolve_api_key({"AGENT_API_KEY": "  env-key-123456 "}) == "env-key-123456"
    assert config.resolve_api_key({"AGENT_API_KEY": "   "}) == "file-key-123456"


def test_blank_key_everywhere_is_none():
    assert config.resolve_api_key({"AGENT_API_KEY": ""}) is None
    with pytest.raises(ConfigError):
        config.save_api_key("  ")


@pytest.mark.skipif(sys.platform == "win32", reason="posix modes")
def test_credentials_mode_and_warning():
    config.save_api_key("file-key-123456")
    path = config.credentials_path()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert config.credentials_warning() is None
    os.chmod(path, 0o644)
    assert "chmod 600" in config.credentials_warning()
    config.save_api_key("another-key-1234")  # rewriting restores the mode
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
