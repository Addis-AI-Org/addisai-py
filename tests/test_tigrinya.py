import json

import httpx
import pytest

from addisai import AddisAI


def client_with(handler):
    calls = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    return AddisAI(api_key="sk_test_123", http_client=httpx.Client(transport=httpx.MockTransport(wrapped))), calls


def ok(data):
    return httpx.Response(200, json={"status": "success", "data": data})


def test_chat_sends_target_language_ti():
    def handler(req):
        body = json.loads(req.content)
        assert req.url.path == "/api/v1/chat_generate"
        assert body["target_language"] == "ti"
        return ok({"response_text": "ሰላም", "finish_reason": "STOP",
                   "usage_metadata": {"prompt_token_count": 1, "candidates_token_count": 1, "total_token_count": 2}})

    addis, calls = client_with(handler)
    res = addis.chat.completions.create(language="ti", messages=[{"role": "user", "content": "ሰላም"}])
    assert len(calls) == 1
    assert res["choices"][0]["message"]["content"] == "ሰላም"


def test_stt_sends_language_code_ti_and_keeps_null_confidence():
    def handler(req):
        assert req.url.path == "/api/v2/stt"
        raw = req.content.decode("utf-8", errors="ignore")
        assert '{"language_code": "ti"}' in raw
        return ok({"transcription": "ሎሚ ጽቡቕ መዓልቲ እዩ።", "confidence": None, "usage_metadata": {"seconds": 2}})

    addis, _ = client_with(handler)
    out = addis.speech.transcribe(audio=b"RIFFfake", language="ti")
    assert out["text"] == "ሎሚ ጽቡቕ መዓልቲ እዩ።"
    assert out["confidence"] is None


@pytest.mark.parametrize("source,target", [("en", "ti"), ("ti", "am"), ("om", "ti")])
def test_translate_tigrinya_directions(source, target):
    def handler(req):
        body = json.loads(req.content)
        assert body["source_language"] == source
        assert body["target_language"] == target
        return ok({"translation": "x", "source_language": source, "target_language": target, "quality": "high"})

    addis, _ = client_with(handler)
    out = addis.translate.create(text="Hello", source=source, target=target)
    assert out["source_language"] == source
    assert out["target_language"] == target


def test_voice_estimate_accepts_every_native_tigrinya_voice():
    voices = ["ti-berhane", "ti-senait", "ti-haben", "ti-rahel", "ti-filimon", "ti-danait", "ti-yonas"]
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append((body["language"], body["voice_id"]))
        return ok({"estimated_cost": 1, "currency": "ETB", "characters": 4, "balance": 10})

    addis, _ = client_with(handler)
    for voice_id in voices:
        addis.voice.estimate(voice_id=voice_id, language="ti", text="ሰላም")
    assert seen == [("ti", v) for v in voices]
