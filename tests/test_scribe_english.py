"""English on Addis Scribe (2026-11-13): language="en" is sent exactly like the other non-Amharic languages."""
import typing

import httpx

from addisai import AddisAI, ScribeLanguage


def result(**extra):
    text = "Good morning everyone."
    return {"text": text, "request_id": "en1", "seconds": 2, "compute_ms": 5, "backend": "turbo", "chunk": "1120ms",
            "mode": "offline", "language": "en", "model": "addis-scribe-english-streaming",
            "usage": {"record_id": "ledger", "characters": len(text), "price_per_1000_characters": 3.5, "credits_used": .08,
                      "credits_remaining": 9.92, "currency": "ETB", "settled": True}, **extra}


def recording(seen, response):
    def handler(request):
        seen.append(request)
        return response
    return AddisAI(api_key="test-secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_english_is_a_scribe_language():
    assert "en" in typing.get_args(ScribeLanguage)


def test_english_upload_with_speakers_sends_the_language():
    seen = []
    out = recording(seen, httpx.Response(200, json={"data": result()})).scribe.transcribe(
        audio=b"audio", request_id="en1", language="en", timestamps="word", speakers=True)
    assert dict(seen[0].url.params) == {"backend": "turbo", "chunk": "1120ms", "request_id": "en1", "timestamps": "word",
                                        "speakers": "true", "language": "en", "stream": "false"}
    assert out["language"] == "en" and out["model"] == "addis-scribe-english-streaming"
