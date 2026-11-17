import os

import pytest

from agent import secrets


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(tmp_path / "_global_cfg"))
    for name in list(os.environ):
        if secrets.secret_name(name):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("AGENT_DEBUG", raising=False)
