"""Environment resolution and security guards."""
from __future__ import annotations

from urllib.parse import urlparse

DEFAULT_BASE_URL = "https://api.addisassistant.com"
API_KEY_ENV_VAR = "ADDIS_API_KEY"

_BLOCKED_HOST_SUFFIXES = (".supabase.co", ".supabase.in")


def resolve_base_url(base_url: str | None) -> str:
    raw = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    is_local = host in ("localhost", "127.0.0.1")

    if parsed.scheme != "https" and not is_local:
        raise ValueError(f'addisai: base_url must use https (got "{parsed.scheme}://{host}").')

    if any(host.endswith(suffix) for suffix in _BLOCKED_HOST_SUFFIXES):
        raise ValueError(
            "addisai: pointing the SDK at a raw *.supabase.co host is not allowed. "
            f"Use the Addis AI API at {DEFAULT_BASE_URL}."
        )
    return raw


def redact_api_key(key: str | None) -> str:
    if not key:
        return "(none)"
    if len(key) <= 8:
        return "••••"
    return f"{key[:4]}••••{key[-2:]}"
