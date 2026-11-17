from agent import config
from agent.cli import select_workspace


def stub(answers):
    it = iter(answers)

    def input_fn(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return input_fn


def test_reprompts_on_bad_input(tmp_path):
    msgs = []
    ws = select_workspace(None, stub(["/does/not/exist", str(tmp_path / "f"), str(tmp_path)]), {}, msgs.append)
    assert ws.root == tmp_path.resolve() and len(msgs) == 2


def test_not_a_directory_rejected(tmp_path):
    f = tmp_path / "f"
    f.write_text("x")
    msgs = []
    ws = select_workspace(None, stub([str(f), str(tmp_path)]), {}, msgs.append)
    assert "not a directory" in msgs[0] and ws is not None


def test_enter_uses_remembered(tmp_path):
    ws = select_workspace(None, stub([""]), {"last_workspace": str(tmp_path)}, lambda m: None)
    assert ws.root == tmp_path.resolve()


def test_remembered_gone_is_dropped(tmp_path):
    prompts = []

    def input_fn(prompt):
        prompts.append(prompt)
        return str(tmp_path)
    select_workspace(None, input_fn, {"last_workspace": str(tmp_path / "gone")}, lambda m: None)
    assert "Enter" not in prompts[0]


def test_bad_flag_falls_through(tmp_path):
    msgs = []
    ws = select_workspace("/nope/nope", stub([str(tmp_path)]), {}, msgs.append)
    assert ws.root == tmp_path.resolve() and "--workspace" in msgs[0]


def test_good_flag_skips_prompt(tmp_path):
    assert select_workspace(str(tmp_path), stub([]), {}, print).root == tmp_path.resolve()


def test_eof_returns_none():
    assert select_workspace(None, stub([]), {}, lambda m: None) is None


def test_state_round_trip(tmp_path):
    config.save_last_workspace(str(tmp_path))
    assert config.load_state()["last_workspace"] == str(tmp_path)
