import json

from agent.context import ContextManager
from agent.loop import AgentLoop
from agent.providers import ProviderError, Response, ToolCall
from agent.providers.fake import FakeProvider
from agent import config
from agent.permissions import PermissionGate
from agent.tools import build_tools
from agent.workspace import Workspace


def call(name, args, id="c1", raw=None):
    return ToolCall(id, name, args, raw if raw is not None else json.dumps(args))


def make(tmp_path, script, max_steps=25, perms=None, confirm=None, session_allow=None, provider=None):
    events = []
    provider = provider or FakeProvider(script)
    overrides = {"max_steps": max_steps}
    if perms:
        overrides["permissions"] = perms
    settings = config.load_settings(tmp_path, overrides).settings
    ws = Workspace.validate(str(tmp_path))
    gate = PermissionGate(settings, confirm or (lambda p: "no"),
                          session_allow if session_allow is not None else set(), ws)
    context = ContextManager(provider, settings)
    loop = AgentLoop(provider, build_tools(), ws, settings, gate, context, lambda k, t: events.append((k, t)))
    return loop, provider, events


def test_tool_call_then_stop(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    loop, provider, _ = make(tmp_path, [
        Response(tool_calls=[call("read_file", {"path": "a.txt"})]),
        Response(text="done"),
    ])
    result = loop.run_task("read it")
    assert result.outcome == "done" and result.final_text == "done"
    tool_msgs = [m for m in provider.calls[1] if m["role"] == "tool"]
    assert tool_msgs == [{"role": "tool", "tool_call_id": "c1", "content": "1\thello"}]


def test_step_limit(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    loop, _, events = make(tmp_path, [
        Response(tool_calls=[call("read_file", {"path": "a.txt"}, id=f"c{i}")]) for i in range(5)
    ], max_steps=2)
    result = loop.run_task("go")
    assert result.outcome == "step_limit" and result.steps == 2
    assert ("error", "stopped after 2 steps") in events


def test_provider_error_ends_task(tmp_path):
    loop, _, events = make(tmp_path, [ProviderError("auth failed for model x")])
    assert loop.run_task("go").outcome == "provider_error"
    assert ("error", "auth failed for model x") in events


def test_unknown_tool_and_bad_args_recoverable(tmp_path):
    loop, provider, _ = make(tmp_path, [
        Response(tool_calls=[call("nope", {}, id="a"), call("read_file", {}, id="b")]),
        Response(text="ok"),
    ])
    assert loop.run_task("go").outcome == "done"
    tool_msgs = [m for m in provider.calls[1] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["a", "b"]
    assert "unknown tool nope" in tool_msgs[0]["content"]
    assert "bad arguments" in tool_msgs[1]["content"]


def test_parse_error_call(tmp_path):
    bad = ToolCall("p", "read_file", {"__parse_error": "{oops"}, "{oops")
    loop, provider, _ = make(tmp_path, [Response(tool_calls=[bad]), Response(text="ok")])
    loop.run_task("go")
    second = provider.calls[1]
    assistant = [m for m in second if m["role"] == "assistant"][0]
    assert assistant["tool_calls"][0]["function"]["arguments"] == "{}"
    tool = [m for m in second if m["role"] == "tool"][0]
    assert tool["content"].startswith("ERROR: bad arguments")


def test_raw_arguments_round_trip(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    raw = '{"path":   "a.txt"}'
    loop, provider, _ = make(tmp_path, [
        Response(tool_calls=[call("read_file", {"path": "a.txt"}, raw=raw)]), Response(text="ok")])
    loop.run_task("go")
    assistant = [m for m in provider.calls[1] if m["role"] == "assistant"][0]
    assert assistant["tool_calls"][0]["function"]["arguments"] == raw


def test_interrupt(tmp_path):
    class Boom(FakeProvider):
        def complete(self, messages, tools):
            raise KeyboardInterrupt
    loop, _, _ = make(tmp_path, [], provider=Boom([]))
    assert loop.run_task("go").outcome == "interrupted"


def test_ask_decline_then_always(tmp_path):
    asked = []
    answers = iter(["no", "always"])

    def confirm(prompt):
        asked.append(prompt)
        return next(answers)
    loop, provider, _ = make(tmp_path, [
        Response(tool_calls=[call("write_file", {"path": "a.txt", "content": "x"}, id="w1")]),
        Response(tool_calls=[call("write_file", {"path": "b.txt", "content": "y"}, id="w2"),
                             call("write_file", {"path": "c.txt", "content": "z"}, id="w3")]),
        Response(text="done"),
    ], confirm=confirm)
    loop.run_task("go")
    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").read_text() == "y" and (tmp_path / "c.txt").read_text() == "z"
    assert len(asked) == 2
    tool_msgs = [m for m in provider.calls[1] if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "ERROR: user declined write_file"


def test_deny_still_yields_tool_message(tmp_path):
    loop, provider, _ = make(tmp_path, [
        Response(tool_calls=[call("write_file", {"path": "a.txt", "content": "x"})]),
        Response(text="ok")], perms={"write": "deny"})
    loop.run_task("go")
    assert not (tmp_path / "a.txt").exists()
    tool = [m for m in provider.calls[1] if m["role"] == "tool"]
    assert len(tool) == 1 and "denied by permission settings" in tool[0]["content"]


def test_always_grant_survives_second_task_and_settings_reload(tmp_path):
    shared = set()
    prompts = []

    def confirm(p):
        prompts.append(p)
        return "always"
    loop1, _, _ = make(tmp_path, [
        Response(tool_calls=[call("write_file", {"path": "a.txt", "content": "1"})]), Response(text="x")],
        confirm=confirm, session_allow=shared)
    loop1.run_task("one")
    loop2, _, _ = make(tmp_path, [  # fresh settings and gate, same session_allow set (as the CLI does)
        Response(tool_calls=[call("write_file", {"path": "b.txt", "content": "2"})]), Response(text="x")],
        confirm=confirm, session_allow=shared)
    loop2.run_task("two")
    assert len(prompts) == 1 and (tmp_path / "b.txt").exists()


def test_integration_package_and_pytest(tmp_path):
    import sys
    test_code = "from pkg.calc import add\\n\\ndef test_add():\\n    assert add(1, 2) == 3\\n"
    provider = FakeProvider([
        Response(tool_calls=[call("write_file", {"path": "pkg/__init__.py", "content": ""}, id="1"),
                             call("write_file", {"path": "pkg/calc.py",
                                                 "content": "def add(a, b):\n    return a - b\n"}, id="2"),
                             call("write_file", {"path": "tests/test_calc.py",
                                                 "content": test_code.replace("\\n", "\n")}, id="3")]),
        Response(tool_calls=[call("edit_file", {"path": "pkg/calc.py", "old_text": "a - b",
                                                "new_text": "a + b"}, id="4")]),
        Response(tool_calls=[call("run_shell", {"command": f'"{sys.executable}" -m pytest -q -p no:cacheprovider'},
                                  id="5")]),
        Response(text="all done"),
    ])
    loop, _, _ = make(tmp_path, None, max_steps=10, confirm=lambda p: "always", provider=provider)
    result = loop.run_task("make a package")
    assert result.outcome == "done"
    shell_result = [m for m in provider.calls[3] if m["role"] == "tool"][-1]["content"]
    assert "exit_code: 0" in shell_result and "1 passed" in shell_result


def test_loop_truncates_and_stubs_through_context(tmp_path):
    (tmp_path / "big.txt").write_text("line\n" * 5000)
    script = [Response(tool_calls=[call("read_file", {"path": "big.txt"}, id=f"c{i}")]) for i in range(5)]
    script.append(Response(text="done"))
    loop, provider, _ = make(tmp_path, script)
    assert loop.run_task("read").outcome == "done"
    first_result = [m for m in provider.calls[1] if m["role"] == "tool"][0]["content"]
    assert "omitted" in first_result and "use start_line/end_line" in first_result
    last_call = provider.calls[-1]
    assert any(m["role"] == "tool" and m["content"].startswith("[old read_file result omitted") for m in last_call)


def test_second_task_does_not_see_first(tmp_path):
    loop, provider, _ = make(tmp_path, [Response(text="a"), Response(text="b")])
    loop.run_task("FIRST-REQUEST")
    loop.run_task("second")
    assert "FIRST-REQUEST" not in json.dumps(provider.calls[1])
    assert "Project summary:" in provider.calls[1][1]["content"]
