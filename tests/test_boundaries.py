import ast
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parent.parent / "agent"
CORE = ["loop", "tools", "workspace", "context", "permissions", "changelog"]


def imports(path):
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


@pytest.mark.parametrize("mod", CORE)
def test_core_does_not_import_cli_or_litellm(mod):
    path = AGENT / f"{mod}.py"
    if not path.exists():
        pytest.skip("module not created yet")
    for name in imports(path):
        assert not name.startswith(("agent.cli", "litellm", "agent.providers.litellm_provider")), name
