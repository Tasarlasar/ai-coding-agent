import os
import sys

import pytest

from agent.workspace import PathEscapeError, Workspace, WorkspaceError

symlinks = pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    return Workspace.validate(str(root))


@pytest.fixture
def outside(tmp_path):
    d = tmp_path / "outside"
    d.mkdir()
    (d / "secret.txt").write_text("top secret")
    return d


def test_dotdot_escape(ws):
    with pytest.raises(PathEscapeError):
        ws.resolve("../x")
    with pytest.raises(PathEscapeError):
        ws.resolve("a/../../x")


def test_absolute_outside_and_inside(ws, outside):
    with pytest.raises(PathEscapeError):
        ws.resolve(str(outside / "secret.txt"))
    assert ws.resolve(str(ws.root / "a.txt")) == ws.root / "a.txt"
    assert ws.resolve(".") == ws.root


@symlinks
def test_symlink_to_outside_dir_and_file(ws, outside):
    os.symlink(outside, ws.root / "link_dir")
    os.symlink(outside / "secret.txt", ws.root / "link_file")
    with pytest.raises(PathEscapeError):
        ws.resolve("link_dir/secret.txt")
    with pytest.raises(PathEscapeError):
        ws.resolve("link_file")
    # non-existent write target below a symlinked parent that points outside
    with pytest.raises(PathEscapeError):
        ws.resolve("link_dir/new/file.txt")


@symlinks
def test_symlink_inside_accepted(ws):
    (ws.root / "real").mkdir()
    (ws.root / "real" / "f.txt").write_text("x")
    os.symlink(ws.root / "real", ws.root / "alias")
    assert ws.resolve("alias/f.txt") == ws.root / "real" / "f.txt"


@symlinks
def test_workspace_root_is_symlink(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    w = Workspace.validate(str(link))
    assert w.root == real.resolve()
    assert w.resolve("a.txt") == real.resolve() / "a.txt"
    assert w.rel(w.resolve("sub/a.txt")) == "sub/a.txt"


@pytest.mark.parametrize("bad", ["", "a\0b"])
def test_empty_and_nul_rejected(ws, bad):
    with pytest.raises(PathEscapeError):
        ws.resolve(bad)


def test_validate_errors(tmp_path):
    with pytest.raises(WorkspaceError):
        Workspace.validate(str(tmp_path / "missing"))
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(WorkspaceError):
        Workspace.validate(str(f))
    with pytest.raises(WorkspaceError):
        Workspace.validate("")
