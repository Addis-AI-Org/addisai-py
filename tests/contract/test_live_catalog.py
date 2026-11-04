"""Drift check against the live public API. No key and no cost: these endpoints are public.

Runs in CI's ``drift`` job (``ADDIS_DRIFT=1``) and is skipped elsewhere so offline test runs stay offline."""
import os
import typing

import httpx
import pytest

from addisai import REALTIME_LANGUAGES, ScribeLanguage

BASE = os.environ.get("ADDIS_BASE_URL", "https://api.addisassistant.com").rstrip("/")
pytestmark = pytest.mark.skipif(os.environ.get("ADDIS_DRIFT") != "1", reason="set ADDIS_DRIFT=1 to check the live API")


def get(path):
    response = httpx.get(BASE + path, timeout=30)
    response.raise_for_status()
    return response.json()["data"]


def test_scribe_languages_match_the_sdk():
    live = get("/api/v1/scribe")["languages"]
    assert set(live) == set(typing.get_args(ScribeLanguage))
    assert {code for code, info in live.items() if not info["speakers"]} == {"sw"}
    assert {code for code, info in live.items() if "standard" in info["backends"]} == {"am"}


def test_realtime_languages_match_the_sdk():
    assert tuple(get("/api/v1/realtime")["languages"]) == REALTIME_LANGUAGES
