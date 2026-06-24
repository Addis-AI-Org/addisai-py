"""ULID generation for idempotency keys (no external dependency)."""
from __future__ import annotations

import os
import time

_ENCODING = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32
_TIME_LEN = 10
_RANDOM_LEN = 16


def _encode_time(now_ms: int) -> str:
    out = [""] * _TIME_LEN
    for i in range(_TIME_LEN - 1, -1, -1):
        mod = now_ms % 32
        out[i] = _ENCODING[mod]
        now_ms = (now_ms - mod) // 32
    return "".join(out)


def _encode_random() -> str:
    return "".join(_ENCODING[b % 32] for b in os.urandom(_RANDOM_LEN))


def ulid() -> str:
    """Return a new 26-char, time-sortable ULID."""
    return _encode_time(int(time.time() * 1000)) + _encode_random()
