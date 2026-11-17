import json

from agent.loop import AgentLoop
from agent.providers import ProviderError, Response, ToolCall
from agent.providers.fake import FakeProvider
from agent.workspace import Workspace
from agent.tools import ToolContext, build_tools


def call(name, args, id="c1", raw=None):
    return ToolCall(id, name, args, raw if raw is not None else json.dumps(args))


def make(tmp_path, script, max_steps=25):
    events = []
    provider = FakeProvider(script)
    loop = AgentLoop(provider, build_tools(), ToolContext(Workspace.validate(str(tmp_path))), max_steps,
                     lambda k, t: events.append((k, t)))
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
    loop = AgentLoop(Boom([]), build_tools(), ToolContext(Workspace.validate(str(tmp_path))), 5, lambda k, t: None)
    assert loop.run_task("go").outcome == "interrupted"


def test_gate_interim_modes(tmp_path):
    asked = []
    provider = FakeProvider([
        Response(tool_calls=[call("write_file", {"path": "a.txt", "content": "x"}, id="w1")]),
        Response(tool_calls=[call("write_file", {"path": "b.txt", "content": "y"}, id="w2")]),
        Response(text="done"),
    ])
    answers = iter(["no", "always"])

    def confirm(prompt):
        asked.append(prompt)
        return next(answers)
    loop = AgentLoop(provider, build_tools(), ToolContext(Workspace.validate(str(tmp_path))), 10, lambda k, t: None, confirm)
    loop.run_task("go")
    assert not (tmp_path / "a.txt").exists() and (tmp_path / "b.txt").read_text() == "y"
    assert len(asked) == 2
    tool_msgs = [m for m in provider.calls[1] if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "ERROR: user declined write_file"


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
    loop = AgentLoop(provider, build_tools(), ToolContext(Workspace.validate(str(tmp_path))), 10, lambda k, t: None,
                     lambda p: "always")
    result = loop.run_task("make a package")
    assert result.outcome == "done"
    shell_result = [m for m in provider.calls[3] if m["role"] == "tool"][-1]["content"]
    assert "exit_code: 0" in shell_result and "1 passed" in shell_result
