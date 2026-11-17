import json
import sys

from agent import config
from agent.changelog import ChangeLog
from agent.context import ContextManager
from agent.loop import AgentLoop
from agent.permissions import PermissionGate
from agent.prompts import SYSTEM_PROMPT
from agent.providers import Response, ToolCall
from agent.providers.fake import FakeProvider
from agent.tools import build_tools
from agent.workspace import Workspace


def tc(id, name, **args):
    return ToolCall(id, name, args, json.dumps(args))


def test_kiro_style_flow(tmp_path):
    (tmp_path / "README.md").write_text("demo\n")
    py = f'"{sys.executable}" -c "from pkg.calc import add; assert add(1, 2) == 3; print(\'ok\')"'
    provider = FakeProvider([
        Response(text="Goal: add a calc package.", tool_calls=[tc("1", "list_dir")]),
        Response(text="Plan:\n1. create package\n2. fix bug\n3. run check",
                 tool_calls=[tc("2", "write_file", path="pkg/calc.py", reason="Create add()",
                                content="def add(a, b):\n    return a - b\n"),
                             tc("2b", "write_file", path="pkg/__init__.py", content="")]),
        Response(tool_calls=[tc("3", "edit_file", path="pkg/calc.py", old_text="a - b", new_text="a + b",
                                reason="Fix sign")]),
        Response(tool_calls=[tc("4", "run_shell", command=py, reason="Check add()")]),
        Response(text="Done: pkg/calc.py implements add(); the check passed."),
    ])
    events = []
    settings = config.load_settings(tmp_path, {"permissions": {"write": "allow", "edit": "allow",
                                                               "shell": "allow"}}).settings
    ws = Workspace.validate(str(tmp_path))
    loop = AgentLoop(provider, build_tools(), ws, settings,
                     PermissionGate(settings, lambda p: "no", set(), ws),
                     ContextManager(provider, settings), ChangeLog(ws),
                     lambda k, t: events.append((k, t)))
    result = loop.run_task("create a small package with an add function")
    assert result.outcome == "done" and result.steps == 5
    assert len(provider.calls) == 5 and not provider.script  # no extra model calls

    kinds = [k for k, _ in events]
    first_write = events.index(("tool", "-> write_file pkg/calc.py"))
    plan = next(i for i, (k, t) in enumerate(events) if k == "assistant" and t.startswith("Plan:"))
    assert plan < first_write
    assert kinds[-1] == "info" and kinds[kinds.index("info"):] == ["info"] * (len(kinds) - kinds.index("info"))
    # every tool line is followed by its result line
    for i, (k, _) in enumerate(events):
        if k == "tool":
            assert events[i + 1][0] == "result"
    assert kinds.count("tool") == kinds.count("result") == 5

    log = (tmp_path / ".agent" / "changelog.log").read_text().splitlines()
    entries = [line.split(" | ")[1:] for line in log if not line.startswith("#")]
    assert entries == [["write", "pkg/calc.py", "Create add()"], ["write", "pkg/__init__.py", "(none given)"],
                       ["edit", "pkg/calc.py", "Fix sign"]]
    assert "Check add()" not in "\n".join(log) and "python" not in "\n".join(log)
    assert any("verify:" in t and "-> exit 0" in t for k, t in events if k == "info")


def test_system_prompt_names_phases_and_reason():
    text = SYSTEM_PROMPT.lower()
    for phase in ("understand", "inspect", "plan", "execute", "verify", "report"):
        assert phase in text
    assert "`reason`" in SYSTEM_PROMPT
