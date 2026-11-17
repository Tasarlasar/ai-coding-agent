"""Scripted end-to-end check with a stub provider (no network). Run: .venv/bin/python <this file>"""
import json, os, subprocess, sys, tempfile
from pathlib import Path

tmp = Path(tempfile.mkdtemp()).resolve()
os.environ["AGENT_CONFIG_DIR"] = str(tmp / "gcfg")
for k in list(os.environ):
    if "KEY" in k or "TOKEN" in k:
        del os.environ[k]

from agent import config
from agent.changelog import ChangeLog
from agent.context import ContextManager
from agent.loop import AgentLoop
from agent.permissions import PermissionGate
from agent.providers import Response, ToolCall
from agent.providers.fake import FakeProvider
from agent.tools import build_tools
from agent.workspace import Workspace

results = []
def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}: {name} {detail}")

def tc(i, name, **a):
    return ToolCall(f"c{i}", name, a, json.dumps(a))

def run(ws_path, script, overrides=None, confirm=lambda p: "no"):
    events, prompts = [], []
    def conf(p):
        prompts.append(p); return confirm(p)
    settings = config.load_settings(ws_path, overrides or {}).settings
    ws = Workspace.validate(str(ws_path))
    prov = FakeProvider(script)
    gate = PermissionGate(settings, conf, set(), ws)
    loop = AgentLoop(prov, build_tools(), ws, settings, gate, ContextManager(prov, settings),
                     ChangeLog(ws), lambda k, t: events.append((k, t)))
    return loop.run_task("build a demo"), events, prompts

W = tmp / "ws"; W.mkdir()
(tmp / "outside.txt").write_text("secret")
os.symlink(tmp / "outside.txt", W / "link.txt")
SECRET_CMD = "echo SECRETCMD_12345 > out.txt"

script = [
    Response(tool_calls=[tc(1, "write_file", path="src/app.py", content="x = 1\n", reason="create module")]),
    Response(tool_calls=[tc(2, "write_file", path="tests/test_app.py", content="def test(): pass\n", reason="add test")]),
    Response(tool_calls=[tc(3, "edit_file", path="src/app.py", old_text="x = 1", new_text="x = 2", reason="bump value")]),
    Response(tool_calls=[tc(4, "run_shell", command=SECRET_CMD, reason="check")]),
    Response(text="all done"),
]
res, events, prompts = run(W, script, {"permissions": {"write": "allow", "edit": "allow", "shell": "allow"}})
check("create files", (W / "src/app.py").exists() and (W / "tests/test_app.py").exists())
check("edit file", (W / "src/app.py").read_text() == "x = 2\n")
check("run shell", (W / "out.txt").exists() and "SECRETCMD_12345" in (W / "out.txt").read_text() and res.outcome == "done")
check("allow mode: no prompts", prompts == [])

# permissions enforced
W2 = tmp / "ws2"; W2.mkdir()
s2 = [Response(tool_calls=[tc(1, "write_file", path="a.txt", content="a", reason="r")]),
      Response(tool_calls=[tc(2, "run_shell", command="touch b.txt")]),
      Response(tool_calls=[tc(3, "write_file", path="c.txt", content="c", reason="r")]),
      Response(text="ok")]
answers = iter(["no", "no", "yes"])
res, ev, prompts = run(W2, s2, confirm=lambda p: next(answers))
check("ask mode prompts for write+shell", len(prompts) == 3, str(prompts))
check("declined write not performed", not (W2 / "a.txt").exists() and not (W2 / "b.txt").exists())
check("approved write performed", (W2 / "c.txt").read_text() == "c")
W3 = tmp / "ws3"; W3.mkdir()
res, ev, prompts = run(W3, [Response(tool_calls=[tc(1, "run_shell", command="touch d.txt")]), Response(text="x")],
                       {"permissions": {"shell": "deny"}})
check("deny mode blocks without prompt", prompts == [] and not (W3 / "d.txt").exists())

# path escape
W4 = tmp / "ws4"; W4.mkdir()
os.symlink(tmp / "outside.txt", W4 / "link.txt")
os.symlink(tmp, W4 / "dirlink")
s4 = [Response(tool_calls=[tc(1, "write_file", path="../escape.txt", content="x", reason="r")]),
      Response(tool_calls=[tc(2, "read_file", path="link.txt")]),
      Response(tool_calls=[tc(3, "write_file", path="link.txt", content="pwn", reason="r")]),
      Response(tool_calls=[tc(4, "write_file", path="dirlink/new.txt", content="pwn", reason="r")]),
      Response(text="x")]
res, ev, prompts = run(W4, s4, {"permissions": {"write": "allow"}})
check("../ rejected", not (tmp / "escape.txt").exists())
check("symlink file read/write rejected", (tmp / "outside.txt").read_text() == "secret")
check("symlinked dir write rejected", not (tmp / "new.txt").exists())
check("escapes reported as errors", sum("escapes" in t for k, t in ev if k == "result") >= 4, str([t for k, t in ev if k == "result"]))

# config precedence
W5 = tmp / "ws5"; W5.mkdir()
config.save_setting("global", "permissions.shell", "deny", W5)
config.save_setting("global", "permissions.write", "allow", W5)
config.save_setting("workspace", "permissions.shell", "ask", W5)
ld = config.load_settings(W5)
check("workspace overrides global", ld.settings.permissions["shell"] == "ask" and ld.sources["permissions.shell"] == "workspace")
check("global still applies elsewhere", ld.settings.permissions["write"] == "allow"
      and config.load_settings(W4).settings.permissions["shell"] == "deny")

# changelog
log = (W / ".agent/changelog.log").read_text()
print(log)
check("changelog entries have reasons", "| write | src/app.py | create module" in log and "| edit | src/app.py | bump value" in log)
check("changelog end-of-task summary", "#> Task done: 3 change(s)" in log and "# end" in log)
check("changelog compact", len(log.splitlines()) <= 15 and len(log) < 1000, f"{len(log)} chars")
check("no shell command text in changelog", "SECRETCMD_12345" not in log and "echo" not in log)

# CLI without a directory
env = {**os.environ, "PYTHONPATH": os.getcwd()}
p = subprocess.run([sys.executable, "-m", "agent", "--model", "x"], input="", capture_output=True, text=True, env=env, cwd=tmp)
check("CLI exits without directory (EOF)", p.returncode == 1 and "Workspace directory (required)" in p.stdout, p.stdout[-80:])
p = subprocess.run([sys.executable, "-m", "agent", "--model", "x"], input="/nonexistent_dir_xyz\nbuild something\n", capture_output=True, text=True, env=env, cwd=tmp)
check("CLI rejects bad directory, never runs task", p.returncode == 1 and "does not exist" in p.stdout and "[task" not in p.stdout, p.stdout[-120:])

bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} passed")
sys.exit(1 if bad else 0)
