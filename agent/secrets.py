"""One definition of "secret" shared by the shell env filter and the scrubbers."""
from __future__ import annotations

from typing import Mapping

_SUFFIXES = (
    "_KEY", "_SECRET", "_TOKEN", "_PASSWORD", "_SECRET_ACCESS_KEY",
    "_CREDENTIALS", "_SESSION_TOKEN", "_API_KEY", "_ACCESS_KEY", "_PASSPHRASE",
)
_EXACT = {"AGENT_API_KEY", "PASSWORD", "SECRET", "TOKEN", "APIKEY"}
MIN_SECRET_LEN = 8


def secret_name(name: str) -> bool:
    """Return True if an environment variable name looks like a secret."""
    upper = name.upper()
    return upper in _EXACT or upper.endswith(_SUFFIXES)


def secret_values(env: Mapping[str, str], explicit_key: str | None = None) -> list[str]:
    """Collect secret values from the environment plus an explicit key, longest first."""
    values = [explicit_key] if explicit_key else []
    values += [v for k, v in env.items() if secret_name(k)]
    kept = {v for v in values if v and v.strip() and len(v) >= MIN_SECRET_LEN}
    return sorted(kept, key=len, reverse=True)


def scrub(text: str, secrets: list[str]) -> str:
    """Replace every known secret value in text with ***."""
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text
