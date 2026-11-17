import pytest

litellm = pytest.importorskip("litellm")

from agent.providers.litellm_provider import LiteLLMProvider, map_exception  # noqa: E402


def _exc(cls, *a):
    return cls("body with sk-secret-value", *a)


@pytest.mark.parametrize("factory,expected", [
    (lambda: litellm.AuthenticationError("sk-abc", "openai", "m"), "auth failed for model m"),
    (lambda: litellm.RateLimitError("x", "openai", "m"), "rate limited by provider for model m"),
    (lambda: litellm.ContextWindowExceededError("x", "m", "openai"), "context window exceeded for model m"),
    (lambda: litellm.Timeout("x", "m", "openai"), "provider timed out for model m"),
    (lambda: litellm.APIConnectionError("x", "openai", "m"), "could not reach provider for model m"),
    (lambda: litellm.BadRequestError("x", "m", "openai"), "provider rejected the request for model m"),
    (lambda: RuntimeError("sk-abc"), "provider error (RuntimeError) for model m"),
])
def test_map_exception(factory, expected):
    err = map_exception(factory(), "m")
    assert str(err) == expected and "sk-" not in str(err)


def test_empty_tools_not_forwarded(monkeypatch):
    seen = {}

    def fake_completion(**kw):
        seen.update(kw)
        raise RuntimeError("stop")
    monkeypatch.setattr(litellm, "completion", fake_completion)
    with pytest.raises(Exception):
        LiteLLMProvider("m", "k").complete([], [])
    assert "tools" not in seen
    with pytest.raises(Exception):
        LiteLLMProvider("m", "k").complete([], [{"type": "function"}])
    assert "tools" in seen


def test_provider_error_scrubs_env_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-supersecretvalue")
    monkeypatch.setattr(litellm, "completion",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("sk-supersecretvalue")))
    with pytest.raises(Exception) as ei:
        LiteLLMProvider("m", None).complete([], [])
    assert "sk-supersecretvalue" not in str(ei.value)


def test_preflight(monkeypatch):
    monkeypatch.setattr(litellm, "validate_environment",
                        lambda m: {"keys_in_environment": False, "missing_keys": ["OPENAI_API_KEY"]})
    assert "OPENAI_API_KEY" in LiteLLMProvider.preflight("gpt-4o", None, None)
    assert LiteLLMProvider.preflight("gpt-4o", "k", None) is None
    assert LiteLLMProvider.preflight("gpt-4o", None, "http://localhost") is None
    monkeypatch.setattr(litellm, "validate_environment",
                        lambda m: {"keys_in_environment": False, "missing_keys": []})
    assert "no credentials found" in LiteLLMProvider.preflight("zzz", None, None)
    monkeypatch.setattr(litellm, "validate_environment",
                        lambda m: {"keys_in_environment": True, "missing_keys": []})
    assert LiteLLMProvider.preflight("gpt-4o", None, None) is None
