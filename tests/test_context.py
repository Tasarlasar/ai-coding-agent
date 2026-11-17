import json

import pytest

from agent import config
from agent.context import (STUB_PREFIX, SUMMARY_PREFIX, ContextManager, estimate_tokens,
                           truncate_output)
from agent.providers import ProviderError, Response
from agent.providers.fake import FakeProvider


def settings(budget=2000, limit=500):
    return config.load_settings(None, {"context_budget_tokens": budget, "output_limit_chars": limit}).settings


@pytest.mark.parametrize("n", [500, 501, 5000, 1_000_000])
def test_truncate_bounds(n):
    text = "".join(chr(65 + i % 26) for i in range(n))
    out = truncate_output(text, 500)
    if n <= 500:
        assert out == text
        return
    assert out.startswith(text[:300]) and out.endswith(text[-200:])
    assert f"[omitted {n - 500} chars of {n} total]" in out
    assert len(out) < 500 + 80


def assistant(i, name="read_file", args=None):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"c{i}", "type": "function",
         "function": {"name": name, "arguments": json.dumps(args or {"path": f"f{i}.py"})}}]}


def tool(i, content):
    return {"role": "tool", "tool_call_id": f"c{i}", "content": content}


def history(n_pairs, size=800):
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "task"}]
    for i in range(n_pairs):
        msgs += [assistant(i), tool(i, f"result{i} " + "x" * size)]
    return msgs


def valid_pairing(msgs):
    pending = set()
    for m in msgs:
        if m["role"] == "assistant":
            assert not pending
            pending = {tc["id"] for tc in m.get("tool_calls") or []}
        elif m["role"] == "tool":
            assert m["tool_call_id"] in pending
            pending.discard(m["tool_call_id"])
    return True


def test_stubbing_old_results_only_and_idempotent():
    cm = ContextManager(FakeProvider([]), settings(budget=2_000_000))
    msgs = history(6)
    out = cm.prepare(msgs)
    assert out[3]["content"].startswith(f"{STUB_PREFIX}read_file result omitted: result0")
    assert out[3]["content"].endswith("chars)]")
    assert out[-1] == msgs[-1] and out[-3] == msgs[-3]  # last six messages untouched
    assert msgs[3]["content"].startswith("result0")  # input not mutated
    assert valid_pairing(out)
    assert cm.prepare(out) == out
    small = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}, assistant(0), tool(0, "short"),
             *history(5, size=10)[2:]]
    assert cm.prepare(small)[3]["content"] == "short"


def test_summarize_triggers_above_80_percent():
    fake = FakeProvider([Response(text="Files touched:\n- a.py\nDecisions:\n- x\nOpen items:\n- y")])
    cm = ContextManager(fake, settings(budget=2000))
    msgs = history(12, size=480)  # each result stays under the 500-char stub threshold
    assert estimate_tokens(msgs) > 1600
    out = cm.prepare(msgs)
    assert len(fake.calls) == 1 and fake.tools_seen == [[]]
    assert out[0] == msgs[0] and out[1] == msgs[1]
    assert out[2]["content"].startswith(SUMMARY_PREFIX) and "a.py" in out[2]["content"]
    assert out[3:] == msgs[-8:]  # most recent turns intact
    assert valid_pairing(out)
    rendered = fake.calls[0][1]["content"]  # summarizer sees old turns, not the kept recent ones
    assert "result0" in rendered and "result11" not in rendered


def test_cut_never_separates_tool_calls_from_results():
    fake = FakeProvider([Response(text="note")])
    cm = ContextManager(fake, settings(budget=2000))
    msgs = history(12, size=480)
    msgs.pop()  # last 8 messages now start with a tool result whose assistant message is earlier
    out = cm.prepare(msgs)
    assert valid_pairing(out) and out[2]["content"].startswith(SUMMARY_PREFIX)
    assert out[3]["role"] == "assistant"


def test_no_resummarize_in_band_and_notes_merge():
    # pad the first note so the post-summary estimate lands between 80% and 100% of the budget
    probe = [*history(12, size=480)[:2], {"role": "user", "content": SUMMARY_PREFIX + "\n"},
             *history(12, size=480)[-8:]]
    pad = "w" * max(0, (1800 - estimate_tokens(probe)) * 4)
    fake = FakeProvider([Response(text="note one " + pad), Response(text="note two")])
    cm = ContextManager(fake, settings(budget=2000))
    out = cm.prepare(history(12, size=480))
    assert len(fake.calls) == 1
    assert 1600 < estimate_tokens(out) <= 2000
    assert cm.prepare(out) == out and len(fake.calls) == 1  # in the band: suppressed
    out += [assistant(50), tool(50, "y" * 450)]
    out = cm.prepare(out)
    assert len(fake.calls) == 1
    for i in range(60, 75):  # growth beyond 1.2x the post-summary estimate re-enables it
        out += [assistant(i), tool(i, "z" * 480)]
    out = cm.prepare(out)
    assert len(fake.calls) == 2
    assert "note one" in fake.calls[1][1]["content"]  # the previous note is merged, not stacked
    assert sum(1 for m in out if str(m.get("content")).startswith(SUMMARY_PREFIX)) == 1


def test_too_little_old_history_skips_summary():
    fake = FakeProvider([])
    warnings = []
    cm = ContextManager(fake, settings(budget=2000), warnings.append)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u" * 9000}, assistant(0), tool(0, "r")]
    assert cm.prepare(msgs) == msgs and fake.calls == []
    assert len(warnings) == 1
    cm.prepare(msgs)
    assert len(warnings) == 1  # warns once


def test_fallback_note_on_provider_error():
    warnings = []
    cm = ContextManager(FakeProvider([ProviderError("rate limited by provider for model m")]),
                        settings(budget=2000), warnings.append)
    base = history(12, size=480)
    msgs = base[:2] + [assistant(99, "write_file", {"path": "src/new.py", "content": "c"}), tool(99, "ok")] + base[2:]
    out = cm.prepare(msgs)
    note = out[2]["content"]
    assert note.startswith(SUMMARY_PREFIX) and "src/new.py" in note and "summary unavailable" in note
    assert "rate limited" in note and warnings


def test_usage_triggers_summary_and_is_reset():
    fake = FakeProvider([Response(text="note")])
    cm = ContextManager(fake, settings(budget=2000))
    cm.note_usage(1900)
    cm.prepare(history(8, size=50))
    assert len(fake.calls) == 1 and cm.last_usage is None


def test_new_task_has_fresh_context_with_project_summary():
    cm = ContextManager(FakeProvider([]), settings())
    first = cm.start_task("SYS", "Workspace: demo\nsrc/", "task one")
    first.append({"role": "assistant", "content": "worked on a.py"})
    second = cm.start_task("SYS", "Workspace: demo\nsrc/\ntask one (done)", "task two")
    assert len(second) == 2 and second is not first
    assert "task one" not in second[1]["content"].split("Task:")[1]
    assert "worked on a.py" not in json.dumps(second)
    assert second[1]["content"].startswith("Project summary:\nWorkspace: demo")
    assert second[1]["content"].endswith("Task:\ntask two")


def test_add_tool_result_truncates():
    cm = ContextManager(FakeProvider([]), settings(limit=500))
    msgs = []
    cm.add_tool_result(msgs, "c1", "x" * 10_000)
    assert "omitted" in msgs[0]["content"] and len(msgs[0]["content"]) < 1400
