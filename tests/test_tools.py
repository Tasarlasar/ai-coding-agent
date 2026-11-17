import os
import sys
import time

import pytest

from agent.workspace import Workspace
from agent.tools import ToolContext, build_tools, is_agent_dir_path, validate_args

TOOLS = build_tools()


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(Workspace.validate(str(tmp_path)))


def run(ctx, name, **args):
    return TOOLS[name].run(args, ctx)


def test_schemas_and_categories():
    assert {t.category for t in TOOLS.values()} == {"read", "write", "edit", "shell"}
    for name in ("write_file", "edit_file", "run_shell"):
        params = TOOLS[name].schema["function"]["parameters"]
        assert "reason" in params["properties"] and "reason" not in params["required"]


def test_validate_args():
    schema = TOOLS["read_file"].schema
    assert validate_args(schema, {"path": "a"}) is None
    assert "missing" in validate_args(schema, {})
    assert "must be string" in validate_args(schema, {"path": 3})
    assert "must be integer" in validate_args(schema, {"path": "a", "start_line": True})


# read_file
def test_read_ranges(ctx):
    (ctx.root / "f.txt").write_text("a\nb\nc\n")
    assert run(ctx, "read_file", path="f.txt").content == "1\ta\n2\tb\n3\tc"
    assert run(ctx, "read_file", path="f.txt", end_line=2).content == "1\ta\n2\tb"
    assert run(ctx, "read_file", path="f.txt", start_line=2, end_line=99).content == "2\tb\n3\tc"
    assert run(ctx, "read_file", path="f.txt", start_line=3, end_line=2).ok is False
    assert run(ctx, "read_file", path="f.txt", start_line=0).ok is False


def test_read_failures(ctx):
    root = ctx.root
    assert not run(ctx, "read_file", path="missing").ok
    (root / "bin").write_bytes(b"ab\0cd")
    assert "binary" in run(ctx, "read_file", path="bin").content
    (root / "big").write_text("x\n" * 600_000)
    assert "start_line" in run(ctx, "read_file", path="big").content
    assert run(ctx, "read_file", path="big", start_line=1, end_line=2).ok


# write_file
def test_write_creates_parents_and_no_reason_needed(ctx):
    r = run(ctx, "write_file", path="a/b/c.txt", content="hi")
    assert r.ok and (ctx.root / "a/b/c.txt").read_text() == "hi"


def test_write_failures(ctx):
    (ctx.root / "d").mkdir()
    assert not run(ctx, "write_file", path="d", content="x").ok
    assert not run(ctx, "write_file", path="x", content="x" * 1_000_001).ok
    assert not run(ctx, "write_file", path=".agent/config.json", content="{}").ok
    assert not (ctx.root / ".agent").exists()


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="case-sensitive filesystem")
def test_agent_dir_guard_case_insensitive(ctx):
    (ctx.root / ".agent").mkdir()
    assert not run(ctx, "write_file", path=".AGENT/x", content="x").ok
    assert is_agent_dir_path(ctx.root, ctx.root / ".AGENT" / "x")


# edit_file
def test_edit_success_and_crlf(ctx):
    f = ctx.root / "f.txt"
    f.write_bytes(b"one\r\ntwo\r\nthree\r\n")
    assert run(ctx, "edit_file", path="f.txt", old_text="two", new_text="2").ok
    assert f.read_bytes() == b"one\r\n2\r\nthree\r\n"


@pytest.mark.parametrize("old,msg", [("zzz", "not found"), ("a", "matches 3 times"), ("", "empty")])
def test_edit_errors_leave_file_unchanged(ctx, old, msg):
    f = ctx.root / "f.txt"
    f.write_bytes(b"a a\na\n")
    r = run(ctx, "edit_file", path="f.txt", old_text=old, new_text="X")
    assert not r.ok and msg in r.content
    assert f.read_bytes() == b"a a\na\n"


def test_edit_refuses_non_utf8_and_binary(ctx):
    latin = ctx.root / "l.txt"
    latin.write_bytes(b"caf\xe9 = 1\nx = 2\n")
    r = run(ctx, "edit_file", path="l.txt", old_text="x = 2", new_text="x = 3")
    assert not r.ok and "UTF-8" in r.content
    assert latin.read_bytes() == b"caf\xe9 = 1\nx = 2\n"
    binf = ctx.root / "b.bin"
    binf.write_bytes(b"ab\0cd")
    assert not run(ctx, "edit_file", path="b.bin", old_text="ab", new_text="x").ok
    assert binf.read_bytes() == b"ab\0cd"


def test_edit_utf8_multibyte_preserved(ctx):
    f = ctx.root / "u.txt"
    f.write_bytes("caf\u00e9 a\n".encode())
    assert run(ctx, "edit_file", path="u.txt", old_text=" a", new_text=" b").ok
    assert f.read_bytes() == "caf\u00e9 b\n".encode()


def test_edit_missing_file_and_agent_dir(ctx):
    assert not run(ctx, "edit_file", path="nope", old_text="a", new_text="b").ok
    (ctx.root / ".agent").mkdir()
    (ctx.root / ".agent/c.json").write_text("{}")
    assert not run(ctx, "edit_file", path=".agent/c.json", old_text="{}", new_text="x").ok


# list_dir
def test_list_dir(ctx):
    root = ctx.root
    (root / "b").mkdir()
    (root / "a.txt").write_text("")
    (root / ".agent").mkdir()
    assert run(ctx, "list_dir").content == "a.txt\nb/"
    assert not run(ctx, "list_dir", path="a.txt").ok
    (root / "b" / "x").write_text("")
    assert run(ctx, "list_dir", path="b").content == "x"


def test_list_dir_cap(ctx):
    for i in range(205):
        (ctx.root / f"f{i:03}").write_text("")
    lines = run(ctx, "list_dir").content.splitlines()
    assert len(lines) == 201 and lines[-1] == "... 5 more"


# search
def test_search(ctx):
    root = ctx.root
    (root / "pkg").mkdir()
    (root / "pkg/a.py").write_text("def foo():\n    pass\n")
    (root / "b.txt").write_text("def foo\n")
    (root / ".git").mkdir()
    (root / ".git/c.py").write_text("def foo\n")
    assert run(ctx, "search", pattern="def foo").content.splitlines() == [
        "b.txt:1: def foo", "pkg/a.py:1: def foo():"]
    assert run(ctx, "search", pattern="def foo", glob="*.py").content == "pkg/a.py:1: def foo():"
    assert run(ctx, "search", pattern="def", path="b.txt").content == "b.txt:1: def foo"
    assert run(ctx, "search", pattern="zzz").content == "no matches"
    assert "invalid regex" in run(ctx, "search", pattern="(").content


def test_search_match_cap(ctx):
    (ctx.root / "m.txt").write_text("hit\n" * 150)
    lines = run(ctx, "search", pattern="hit").content.splitlines()
    assert len(lines) == 101 and "stopped at 100" in lines[-1]


# run_shell
def py(code):
    return f'"{sys.executable}" -c "{code}"'


def test_shell_exit_code_cwd(ctx):
    r = run(ctx, "run_shell", command=py("import os;print(os.getcwd())"))
    assert r.ok and "exit_code: 0" in r.content and str(ctx.root) in r.content
    r = run(ctx, "run_shell", command=py("import sys;sys.exit(3)"))
    assert r.ok and "exit_code: 3" in r.content


def test_shell_output_truncated(ctx):
    ctx.settings = type("S", (), {"output_limit_chars": 500, "shell_timeout_s": 60})()
    r = run(ctx, "run_shell", command=py("print('x'*5000)"))
    assert "omitted" in r.content and len(r.content) < 1500


def test_shell_env_stripped(ctx, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret-value-1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value-1")
    monkeypatch.setenv("HOME", "/tmp/somehome")
    r = run(ctx, "run_shell", command=py("import os;print(sorted(os.environ))"))
    assert "HOME" in r.content
    assert "AWS_SECRET_ACCESS_KEY" not in r.content and "OPENAI_API_KEY" not in r.content


def test_shell_huge_output_bounded(ctx):
    ctx.settings = type("S", (), {"output_limit_chars": 500, "shell_timeout_s": 60})()
    r = run(ctx, "run_shell", command=py("import sys;sys.stdout.write('y'*5_000_000)"))
    assert r.ok and "omitted" in r.content and len(r.content) < 1500


@pytest.mark.skipif(sys.platform == "win32", reason="posix process groups")
def test_shell_interrupt_kills_group(ctx, monkeypatch):
    import subprocess
    pidfile = ctx.root / "pid2"
    code = f"import os,time;open(r'{pidfile}','w').write(str(os.getpid()));time.sleep(60)"
    orig = subprocess.Popen.wait

    def fake_wait(self, timeout=None):
        if timeout is not None:
            for _ in range(100):
                if pidfile.exists() and pidfile.read_text():
                    break
                time.sleep(0.05)
            raise KeyboardInterrupt
        return orig(self)

    monkeypatch.setattr(subprocess.Popen, "wait", fake_wait)
    with pytest.raises(KeyboardInterrupt):
        run(ctx, "run_shell", command=py(code))
    pid = int(pidfile.read_text())
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.skipif(sys.platform == "win32", reason="posix process groups")
def test_shell_timeout_kills_grandchild(ctx):
    pidfile = ctx.root / "pid"
    code = ("import subprocess,sys,time;"
            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
            f"open(r'{pidfile}','w').write(str(p.pid));time.sleep(60)")
    code = code.replace("\"", "'")
    r = run(ctx, "run_shell", command=py(code), timeout=2)
    assert not r.ok and "timed out after 2s" in r.content
    pid = int(pidfile.read_text())
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


# path confinement (AC10)
@pytest.fixture
def escape_setup(ctx, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "_outside")
    outside.mkdir()
    (outside / "secret.txt").write_text("needle top secret")
    if sys.platform != "win32":
        os.symlink(outside, ctx.root / "link_dir")
        os.symlink(outside / "secret.txt", ctx.root / "link_file")
    return outside


ESCAPES = [("read_file", {"path": "../x"}), ("write_file", {"path": "../x", "content": "c"}),
           ("edit_file", {"path": "../x", "old_text": "a", "new_text": "b"}),
           ("list_dir", {"path": "../"}), ("search", {"pattern": "a", "path": ".."})]


@pytest.mark.parametrize("name,args", ESCAPES)
def test_dotdot_escape_is_error(ctx, escape_setup, name, args):
    r = TOOLS[name].run(args, ctx)
    assert not r.ok and r.content.startswith("ERROR: path escapes workspace")
    assert not (ctx.root.parent / "x").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks")
def test_symlink_escape_no_io(ctx, escape_setup):
    secret = escape_setup / "secret.txt"
    assert "escapes" in run(ctx, "read_file", path="link_file").content
    assert "escapes" in run(ctx, "read_file", path="link_dir/secret.txt").content
    assert "escapes" in run(ctx, "write_file", path="link_dir/new.txt", content="x").content
    assert not (escape_setup / "new.txt").exists()
    assert "escapes" in run(ctx, "write_file", path="link_file", content="x").content
    assert "escapes" in run(ctx, "edit_file", path="link_file", old_text="needle", new_text="n").content
    assert secret.read_text() == "needle top secret"
    assert "escapes" in run(ctx, "list_dir", path="link_dir").content
    assert "escapes" in run(ctx, "search", pattern="needle", path="link_dir").content


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks")
def test_search_skips_symlinked_outside_file(ctx, escape_setup):
    (ctx.root / "inside.txt").write_text("needle inside")
    r = run(ctx, "search", pattern="needle")
    assert r.content == "inside.txt:1: needle inside"
