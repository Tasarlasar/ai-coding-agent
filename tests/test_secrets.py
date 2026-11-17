import pytest

from agent.secrets import scrub, secret_name, secret_values


@pytest.mark.parametrize("name", ["OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                                  "GITHUB_TOKEN", "AGENT_API_KEY", "password", "apikey"])
def test_secret_names(name):
    assert secret_name(name)


@pytest.mark.parametrize("name", ["HOME", "PATH", "LANG", "KEYBOARD"])
def test_non_secret_names(name):
    assert not secret_name(name)


def test_secret_values_filters_and_sorts():
    env = {"A_TOKEN": "", "B_TOKEN": "   ", "C_TOKEN": "short", "D_TOKEN": "abcdefgh",
           "E_TOKEN": "abcdefgh12345", "HOME": "/home/user-long"}
    assert secret_values(env, "explicitkey1") == ["abcdefgh12345", "explicitkey1", "abcdefgh"]


def test_scrub():
    assert scrub("key abcdefgh here", ["abcdefgh"]) == "key *** here"
    assert scrub("nothing", []) == "nothing"
