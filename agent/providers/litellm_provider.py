"""LiteLLM backend. The only module that imports litellm."""
from __future__ import annotations

import json
import os

import litellm

from agent import secrets
from agent.providers import ProviderError, Response, ToolCall


def map_exception(exc: Exception, model: str) -> ProviderError:
    """Map a litellm exception to a fixed one-line message. str(exc) is never used."""
    ex = litellm
    table = (
        (("AuthenticationError", "PermissionDeniedError"), f"auth failed for model {model}"),
        (("RateLimitError",), f"rate limited by provider for model {model}"),
        (("ContextWindowExceededError",), f"context window exceeded for model {model}"),
        (("Timeout",), f"provider timed out for model {model}"),
        (("APIConnectionError", "ServiceUnavailableError"), f"could not reach provider for model {model}"),
        (("BadRequestError", "NotFoundError"), f"provider rejected the request for model {model}"),
    )
    for names, message in table:
        classes = tuple(getattr(ex, n) for n in names if hasattr(ex, n))
        if classes and isinstance(exc, classes):
            return ProviderError(message)
    return ProviderError(f"provider error ({type(exc).__name__}) for model {model}")


class LiteLLMProvider:
    """Provider backed by LiteLLM, for any model or OpenAI-compatible endpoint."""
    def __init__(self, model: str, api_key: str | None = None,
                 api_base: str | None = None, timeout: float = 120):
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.timeout = timeout

    def complete(self, messages: list[dict], tools: list[dict]) -> Response:
        """Call the model through LiteLLM and map failures to a scrubbed ProviderError."""
        extra: dict = {}
        if tools:
            extra["tools"] = tools
        try:
            raw = litellm.completion(
                model=self.model, messages=messages, api_key=self.api_key,
                api_base=self.api_base, timeout=self.timeout, **extra,
            )
        except Exception as exc:  # noqa: BLE001 - mapped to a fixed message
            err = map_exception(exc, self.model)
            msg = secrets.scrub(str(err), secrets.secret_values(os.environ, self.api_key))
            raise ProviderError(msg) from None
        return self._parse(raw)

    @staticmethod
    def _parse(raw) -> Response:
        message = raw.choices[0].message
        calls: list[ToolCall] = []
        for tc in getattr(message, "tool_calls", None) or []:
            args_raw = tc.function.arguments or "{}"
            try:
                parsed = json.loads(args_raw)
            except (ValueError, TypeError):
                parsed = None
            if not isinstance(parsed, dict):
                parsed = {"__parse_error": args_raw}
            calls.append(ToolCall(id=tc.id, name=tc.function.name,
                                  arguments=parsed, raw_arguments=args_raw))
        usage = getattr(raw, "usage", None)
        total = getattr(usage, "total_tokens", None) if usage else None
        return Response(text=message.content or None, tool_calls=calls, usage_total_tokens=total)

    @staticmethod
    def preflight(model: str | None, api_key: str | None, api_base: str | None) -> str | None:
        """Return a problem description if no credentials or api_base are available, else None."""
        if api_key or api_base:
            return None
        try:
            info = litellm.validate_environment(model)
        except Exception:  # noqa: BLE001
            info = {}
        if info.get("keys_in_environment"):
            return None
        missing = info.get("missing_keys") or []
        if missing:
            return (f"missing credentials for model {model}: {', '.join(missing)}; "
                    "set AGENT_API_KEY or use /config")
        return (f"no credentials found for model {model}; "
                "set AGENT_API_KEY, set api_base, or use /config")
