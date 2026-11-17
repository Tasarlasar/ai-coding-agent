import re

import pytest

from agent.changelog import ChangeLog
from agent.workspace import Workspace


@pytest.fixture
def log(tmp_path):
    return ChangeLog(Workspace.validate(str(tmp_path)))


def lines(log):
    return log.path.read_text(encoding="utf-8").splitlines()


def test_exact_line_format(log):
    log.begin_task("Add a CLI entry point")
    log.record("write", "src/app.py", "Create entry point")
    log.record("edit", "src/app.py", "Fix off-by-one")
    log.end_task("done text", "done")
    ls = lines(log)
    assert re.fullmatch(r"# task \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d \| Add a CLI entry point", ls[0])
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d \| write \| src/app.py \| Create entry point", ls[1])
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d \| edit \| src/app.py \| Fix off-by-one", ls[2])
    assert ls[-1].endswith(" done | 2 changes") and ls[-1].startswith("# end ")
    task_id = ls[0].split(" ")[2]
    assert ls[-1].startswith(f"# end {task_id} ")


def test_sanitizing_and_missing_reason(log):
    log.begin_task("t")
    log.record("write", "a|b.py", "line one\nline | two   " + "x" * 400)
    log.record("write", "c.py", None)
    log.record("write", "d.py", "   ")
    ls = lines(log)
    assert ls[1].count(" | ") == 3 and "\n" not in ls[1]
    assert len(ls[1].split(" | ")[3]) == 200
    assert ls[2].endswith("| (none given)") and ls[3].endswith("| (none given)")


def test_no_entries_for_reads_or_shell(log):
    log.begin_task("t")
    log.record_verification("pytest -q", 0)
    assert len(lines(log)) == 1  # only the task header


def test_shell_command_text_never_in_file(log):
    log.begin_task("run tests")
    log.record_verification("pytest --key sk-SECRET " + "y" * 200, 0)
    terminal = log.end_task("ok", "done")
    text = log.path.read_text()
    assert "sk-SECRET" not in text and "pytest" not in text
    assert "#> verify: 1 shell run(s), last exit 0" in text
    shown = [t for t in terminal if "verify:" in t][0]
    assert "pytest --key sk-SECRET" in shown and len(shown) <= 2 + len("verify: ") + 80 + len(" -> exit 0") + 1


def test_no_verify_line_without_shell_runs(log):
    log.begin_task("t")
    log.end_task(None, "done")
    assert not any("verify" in line for line in lines(log))


def test_pairing_and_unfinished(log):
    log.begin_task("first task")
    log.end_task(None, "done")
    log.begin_task("second task")
    log.end_task(None, "step_limit")
    log.begin_task("third, never finished")
    summary = log.project_summary()
    assert "- first task (done)" in summary
    assert "- second task (step_limit)" in summary
    assert "- third, never finished (unfinished)" in summary


def test_same_second_tasks_pair_correctly(log):
    for name in ("a", "b", "c"):
        log.begin_task(name)
        log.end_task(None, "done")
    assert [t for t in log._recent_tasks()] == ["a (done)", "b (done)", "c (done)"]


def test_file_names_cannot_forge_markers(log):
    log.begin_task("t")
    log.record("write", "end x", "r")
    log.record("write", "task y", "r")
    log.record("write", "\n# end FAKE done | 0 changes", "r")
    log.end_task(None, "done")
    starts = [line for line in lines(log) if line.startswith(("# task ", "# end "))]
    assert len(starts) == 2
    summary_lines = [line for line in lines(log) if line.startswith("#> ")]
    assert "#>   end x: r" in summary_lines and "#>   task y: r" in summary_lines
    assert log._recent_tasks() == ["t (done)"]


def test_summary_limits(log):
    log.begin_task("t")
    for i in range(12):
        log.record("write", f"f{i}.py", f"reason {i}")
    for i in range(6):
        log.record_verification(f"cmd{i}", i)
    terminal = log.end_task(None, "done")
    assert len(terminal) <= 15
    assert sum(1 for t in terminal if t.startswith("  f")) == 8 and "  +4 more" in terminal
    assert sum(1 for t in terminal if "verify:" in t) == 4 and "cmd0" not in " ".join(terminal)
    assert terminal[0] == "Task done: 12 change(s)"


def test_changed_file_last_reason_wins(log):
    log.begin_task("t")
    log.record("write", "a.py", "first")
    log.record("edit", "a.py", "second")
    assert "  a.py: second" in log.end_task(None, "done")


def test_project_summary_cap_and_empty(tmp_path, log):
    assert log.project_summary() == f"Workspace: {tmp_path.name}\nTop-level: (empty)"
    for i in range(300):
        (tmp_path / f"{'n' * 20}{i}.txt").write_text("")
    assert len(log.project_summary()) <= 1500


def test_log_has_no_diff_content(log):
    log.begin_task("t")
    log.record("edit", "a.py", "tweak")
    log.end_task(None, "done")
    assert not any(line.startswith(("+", "-", "@@")) for line in lines(log))


def test_append_failure_is_reported_not_raised(tmp_path):
    ws = Workspace.validate(str(tmp_path))
    (tmp_path / ".agent").write_text("a file, not a directory")
    log = ChangeLog(ws)
    log.begin_task("t")
    log.record("write", "a.py", "r")
    assert log.pop_error() and log.pop_error() is None
