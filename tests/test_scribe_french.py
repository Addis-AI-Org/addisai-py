"""French on Addis Scribe (2026-11-15): language="fr" is sent exactly like the other non-Amharic languages."""
import typing

import httpx

from addisai import AddisAI, ScribeLanguage


def result(**extra):
    text = "Bonjour à tous."
    return {"text": text, "request_id": "fr1", "seconds": 2, "compute_ms": 5, "backend": "turbo", "chunk": "1120ms",
            "mode": "offline", "language": "fr", "model": "addis-scribe-french-streaming",
            "usage": {"record_id": "ledger", "characters": len(text), "price_per_1000_characters": 3.5, "credits_used": .05,
                      "credits_remaining": 9.95, "currency": "ETB", "settled": True}, **extra}


def recording(seen, response):
    def handler(request):
        seen.append(request)
        return response
    return AddisAI(api_key="test-secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_french_is_a_scribe_language_after_english():
    assert typing.get_args(ScribeLanguage)[-2:] == ("en", "fr")


def test_french_upload_sends_the_language():
    seen = []
    out = recording(seen, httpx.Response(200, json={"data": result()})).scribe.transcribe(
        audio=b"audio", request_id="fr1", language="fr", timestamps="word")
    assert dict(seen[0].url.params) == {"backend": "turbo", "chunk": "1120ms", "request_id": "fr1", "timestamps": "word",
                                        "language": "fr", "stream": "false"}
    assert out["language"] == "fr" and out["model"] == "addis-scribe-french-streaming"
