import os
import sys

import pytest

from agent import config
from agent.permissions import PermissionGate, resolve_mode
from agent.tools import build_tools
from agent.workspace import Workspace

TOOLS = build_tools()


def gate_for(tmp_path, perms, answers=(), session=None):
    settings = config.load_settings(tmp_path, {"permissions": perms}).settings
    calls = []
    it = iter(answers)

    def confirm(prompt):
        calls.append(prompt)
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    gate = PermissionGate(settings, confirm, session if session is not None else set(),
                          Workspace.validate(str(tmp_path)))
    return gate, calls


def test_resolve_mode_defaults_and_merge(tmp_path):
    s = config.load_settings(tmp_path).settings
    assert [resolve_mode(c, s) for c in config.CATEGORIES] == ["allow", "ask", "ask", "ask"]
    s = config.load_settings(tmp_path, {"permissions": {"shell": "deny"}}).settings
    assert resolve_mode("shell", s) == "deny" and resolve_mode("write", s) == "ask"


def test_allow_does_not_prompt(tmp_path):
    gate, calls = gate_for(tmp_path, {"write": "allow"})
    assert gate.check(TOOLS["write_file"], {"path": "a", "content": ""}) == (True, "")
    assert gate.check(TOOLS["read_file"], {"path": "a"}) == (True, "")
    assert calls == []


def test_deny_blocks_without_prompt(tmp_path):
    gate, calls = gate_for(tmp_path, {"shell": "deny"}, ["yes"])
    ok, msg = gate.check(TOOLS["run_shell"], {"command": "ls"})
    assert not ok and msg == "ERROR: run_shell is denied by permission settings" and calls == []


def test_ask_yes_no_always_eof(tmp_path):
    session = set()
    gate, calls = gate_for(tmp_path, {}, ["yes", "no", "always"], session)
    edit = TOOLS["edit_file"]
    args = {"path": "a.txt", "old_text": "a", "new_text": "b", "reason": "fix"}
    assert gate.check(edit, args) == (True, "")
    assert gate.check(edit, args) == (False, "ERROR: user declined edit_file")
    assert gate.check(edit, args) == (True, "") and session == {"edit"}
    assert gate.check(edit, args) == (True, "")  # session grant: no 4th prompt
    assert len(calls) == 3 and "fix" in calls[0] and "a.txt" in calls[0]
    gate2, _ = gate_for(tmp_path, {}, [])  # EOF on confirm counts as no
    assert gate2.check(TOOLS["run_shell"], {"command": "ls"}) == (False, "ERROR: user declined run_shell")


def test_shell_prompt_truncates_command(tmp_path):
    gate, calls = gate_for(tmp_path, {}, ["yes"])
    gate.check(TOOLS["run_shell"], {"command": "x" * 500})
    assert len(calls[0]) < 260


def test_escape_has_zero_confirm_calls(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "_o")
    outside.mkdir()
    (outside / "f").write_text("x")
    paths = ["../x", str(outside / "f")]
    if sys.platform != "win32":
        os.symlink(outside, tmp_path / "link")
        paths.append("link/f")
    gate, calls = gate_for(tmp_path, {"write": "ask", "read": "ask"}, ["yes"] * 10)
    for p in paths:
        for name in ("read_file", "write_file", "edit_file", "list_dir", "search"):
            args = {"path": p, "content": "", "old_text": "a", "new_text": "b", "pattern": "a"}
            ok, msg = gate.check(TOOLS[name], args)
            assert not ok and msg.startswith("ERROR: path escapes workspace")
    assert calls == []


def test_overwrite_vs_write_prompt(tmp_path):
    (tmp_path / "old.txt").write_text("x")
    gate, calls = gate_for(tmp_path, {}, ["yes", "yes"])
    gate.check(TOOLS["write_file"], {"path": "old.txt", "content": ""})
    gate.check(TOOLS["write_file"], {"path": "new.txt", "content": ""})
    assert "overwrite" in calls[0] and "overwrite" not in calls[1] and "write" in calls[1]
