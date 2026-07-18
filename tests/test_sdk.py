import json

import httpx
import pytest

import addisai
from addisai import (
    AddisAI,
    AuthenticationError,
    IdempotencyConflictError,
    InsufficientCreditsError,
    RateLimitError,
    ulid,
)
from addisai._env import resolve_base_url, redact_api_key
from addisai._exceptions import make_api_error


def client_with(handler):
    """Build an AddisAI client whose HTTP layer is a MockTransport."""
    calls = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(wrapped))
    return AddisAI(api_key="sk_test_123", http_client=http), calls


def json_response(body, status=200, headers=None):
    return httpx.Response(status, json=body, headers=headers or {})


# --- security guards -------------------------------------------------------

def test_requires_api_key(monkeypatch):
    monkeypatch.delenv("ADDIS_API_KEY", raising=False)
    with pytest.raises(addisai.AddisAIError):
        AddisAI()


def test_rejects_supabase_host():
    with pytest.raises(ValueError):
        resolve_base_url("https://vzootpcpzepaeirdnbvx.supabase.co/functions/v1")


def test_rejects_non_https():
    with pytest.raises(ValueError):
        resolve_base_url("http://api.addisassistant.com")
    assert "localhost" in resolve_base_url("http://localhost:54321")


def test_default_base_url():
    assert resolve_base_url(None) == "https://api.addisassistant.com"


def test_redaction():
    assert redact_api_key("sk_live_abcdef1234") == "sk_l••••34"
    assert "abcdef" not in repr(AddisAI(api_key="sk_live_abcdef1234"))


# --- ulid ------------------------------------------------------------------

def test_ulid():
    import time

    a = ulid()
    assert len(a) == 26
    assert a != ulid()  # unique
    time.sleep(0.002)
    assert a < ulid()  # time-sortable across a time gap


# --- error normalization ---------------------------------------------------

def test_error_mapping():
    assert isinstance(make_api_error(401, {"error": {"code": "X", "message": "x"}}, "", {}), AuthenticationError)
    assert isinstance(make_api_error(402, {"error": {"code": "INSUFFICIENT_CREDITS", "message": "x"}}, "", {}), InsufficientCreditsError)
    e = make_api_error(409, {"error": {"code": "IDEMPOTENCY_CONFLICT", "message": "x"}}, "", {})
    assert isinstance(e, IdempotencyConflictError)


def test_rate_limit_headers():
    e = make_api_error(429, {"error": {"code": "RATE_LIMITED", "message": "x"}}, "", {"retry-after": "12", "x-ratelimit-remaining": "0"})
    assert isinstance(e, RateLimitError)
    assert e.retry_after == 12
    assert e.remaining == 0


def test_legacy_status_error_envelope():
    e = make_api_error(400, {"status": "error", "error": {"code": "INVALID_INPUT", "message": "bad"}}, "", {})
    assert e.code == "INVALID_INPUT"
    assert str(e) == "bad"


# --- voice.generate --------------------------------------------------------

def test_voice_generate_maps_clip_and_idempotency():
    def handler(req):
        body = json.loads(req.content)
        assert req.url.path == "/api/v1/voice/generations"
        assert len(body["client_request_id"]) == 26
        assert body["voice_id"] == "am-hamen"
        return json_response({"data": {
            "id": "clip_1", "text": "ሰላም", "text_preview": "ሰላም",
            "voice_id": "am-hamen", "voice_name": "Hamen", "voice_descriptor": "Warm",
            "language": "am", "output_format": "mp3_44100",
            "audio_url": "https://cdn.addisassistant.com/audio/clips/clip_1.mp3?token=x",
            "mime_type": "audio/mpeg", "duration_seconds": 1.2,
            "character_count": 3, "billable_characters": 3, "download_name": "x.mp3",
            "created_at": "2026-06-14T00:00:00Z",
            "usage": {"pricing_unit": "minute", "price_per_minute": 5, "price_per_audio_minute": 5, "credits_used": 0.1, "credits_remaining": 499.9, "currency": "ETB"},
            "meta": {"ignored_voice_settings": ["style"], "applied_provider_settings": {"exaggeration": 0.5}, "idempotent_replay": False},
        }})

    addis, _ = client_with(handler)
    clip = addis.voice.generate(voice_id="am-hamen", text="ሰላም", language="am")
    assert clip.id == "clip_1"
    assert "cdn.addisassistant.com" in clip.audio_url
    assert clip.usage["currency"] == "ETB"
    assert clip.usage["pricing_unit"] == "minute"
    assert clip.usage["price_per_minute"] == 5
    # Security: provider knobs are not exposed.
    assert "applied_provider_settings" not in clip.meta
    assert clip.meta["ignored_voice_settings"] == ["style"]


def test_voice_generate_insufficient_credits():
    def handler(req):
        return json_response({"error": {"code": "INSUFFICIENT_CREDITS", "message": "low", "details": []}}, status=402)

    addis, _ = client_with(handler)
    with pytest.raises(InsufficientCreditsError):
        addis.voice.generate(voice_id="am-hamen", text="x", language="am")


def test_voice_estimate_and_usage_use_minute_pricing():
    def handler(req):
        if req.url.path == "/api/v1/voice/estimate":
            return json_response({"data": {
                "character_count": 20,
                "billable_characters": 20,
                "pricing_unit": "minute",
                "price_per_minute": 5,
                "price_per_audio_minute": 5,
                "estimated_duration_seconds": 2,
                "estimated_billable_seconds": 2,
                "estimated_billable_minutes": 0.0333,
                "estimated_cost": 0.1667,
                "currency": "ETB",
                "current_balance": 500,
                "estimated_balance_after": 499.8333,
                "can_generate": True,
            }})
        return json_response({"data": {
            "wallet_id": "wallet_1",
            "balance": 500,
            "formatted_balance": "Br 500.00",
            "currency": "ETB",
            "last_deduction_at": None,
            "total_spend": 0,
            "formatted_total_spend": "Br 0.00",
            "max_tts_characters": 5000,
            "pricing": {
                "unit": "minute",
                "price_per_minute": 5,
                "price_per_audio_minute": 5,
                "minimum_charge": 0,
                "currency": "ETB",
            },
            "budget": None,
        }})

    addis, _ = client_with(handler)
    estimate = addis.voice.estimate(voice_id="am-hamen", text="ሰላም", language="am")
    usage = addis.voice.usage()

    assert estimate["pricing_unit"] == "minute"
    assert estimate["price_per_minute"] == 5
    assert estimate["estimated_billable_minutes"] == 0.0333
    assert usage["pricing"]["unit"] == "minute"
    assert usage["pricing"]["price_per_minute"] == 5


# --- chat ------------------------------------------------------------------

def test_chat_maps_to_native_and_hides_model():
    def handler(req):
        body = json.loads(req.content)
        assert req.url.path == "/api/v1/chat_generate"
        assert "model" not in body
        assert body["prompt"] == "Capital of Ethiopia?"
        assert len(body["conversation_history"]) == 2
        assert body["target_language"] == "am"
        assert body["system"] == "Be concise."
        return json_response({
            "status": "success",
            "data": {
                "response_text": "Addis Ababa", "finish_reason": "STOP",
                "usage_metadata": {"prompt_token_count": 5, "candidates_token_count": 2, "total_token_count": 7},
                "modelVersion": "internal-should-be-hidden",
            },
        })

    addis, _ = client_with(handler)
    res = addis.chat.completions.create(
        model="gpt-4o", language="am", system="Be concise.",
        messages=[
            {"role": "user", "content": "Tell me about coffee."},
            {"role": "assistant", "content": "Coffee is Ethiopian."},
            {"role": "user", "content": "Capital of Ethiopia?"},
        ],
    )
    assert res["model"] == "addis-1-alef"
    assert res["choices"][0]["message"]["content"] == "Addis Ababa"
    assert res["choices"][0]["finish_reason"] == "stop"


def test_auth_sends_api_key_header_only():
    captured = {}

    def handler(req):
        captured["x_api_key"] = req.headers.get("x-api-key")
        captured["authorization"] = req.headers.get("authorization")
        return json_response({"status": "success", "data": {"translation": "ok", "source_language": "en", "target_language": "am", "quality": None}})

    addis, _ = client_with(handler)
    addis.translate.create(text="Hi", source="en", target="am")
    assert captured["x_api_key"] == "sk_test_123"
    assert captured["authorization"] is None


# --- translate -------------------------------------------------------------

def test_translate():
    def handler(req):
        body = json.loads(req.content)
        assert body["source_language"] == "en"
        return json_response({"status": "success", "data": {"translation": "ሰላም", "source_language": "en", "target_language": "am", "quality": "high"}})

    addis, _ = client_with(handler)
    out = addis.translate.create(text="Hello", source="en", target="am")
    assert out["text"] == "ሰላም"
    assert out["quality"] == "high"


# --- legacy ----------------------------------------------------------------

def test_legacy_audio_deprecated_bridge():
    import base64

    import addisai.resources.legacy as legacy_mod

    legacy_mod._warned = False  # ensure the one-time warning fires here

    audio_b64 = base64.b64encode(b"RIFFfake").decode()

    def handler(req):
        body = json.loads(req.content)
        assert req.url.path == "/api/v1/audio"
        assert body["stream"] is False
        return json_response({"audio": audio_b64})

    addis, _ = client_with(handler)
    with pytest.warns(DeprecationWarning):
        out = addis.legacy.audio.generate(text="ሰላም", language="am")
    assert out.content() == b"RIFFfake"


# --- streaming -------------------------------------------------------------

_SSE = (
    'data: {"type":"metadata","transcription_raw":"r","transcription_clean":"c"}\n\n'
    'data: {"type":"content","text":"Addis ","finish_reason":null}\n\n'
    'data: {"type":"content","text":"Ababa","finish_reason":"STOP","usage_metadata":{"prompt_token_count":5,"candidates_token_count":2,"total_token_count":7}}\n\n'
    "event: done\ndata: [DONE]\n\n"
)


def _stream_response(text, content_type):
    return httpx.Response(200, text=text, headers={"content-type": content_type})


def test_chat_streaming():
    def handler(req):
        body = json.loads(req.content)
        assert req.url.path == "/api/v1/chat_generate"
        assert body["generation_config"]["stream"] is True
        return _stream_response(_SSE, "text/event-stream")

    addis, _ = client_with(handler)
    stream = addis.chat.completions.create(
        language="am", messages=[{"role": "user", "content": "Capital?"}], stream=True
    )
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in stream)
    assert text == "Addis Ababa"
    assert stream.transcription["clean"] == "c"


def test_chat_stream_final_completion():
    addis, _ = client_with(lambda req: _stream_response(_SSE, "text/event-stream"))
    completion = addis.chat.completions.create(
        language="am", messages=[{"role": "user", "content": "x"}], stream=True
    ).final_completion()
    assert completion["choices"][0]["message"]["content"] == "Addis Ababa"
    assert completion["choices"][0]["finish_reason"] == "stop"
    assert completion["usage"]["total_tokens"] == 7


def test_legacy_audio_stream_ndjson():
    import base64

    nd = (
        '{"audio_chunk":"%s","index":0}\n{"audio_chunk":"%s","index":1}\n'
        % (base64.b64encode(b"AB").decode(), base64.b64encode(b"CD").decode())
    )
    addis, _ = client_with(lambda req: _stream_response(nd, "application/x-ndjson"))
    audio = addis.legacy.audio.stream(text="ሰላም", language="am")
    assert audio.read() == b"ABCD"


def test_legacy_audio_stream_raw():
    addis, _ = client_with(lambda req: _stream_response("RIFFwav", "audio/wav"))
    audio = addis.legacy.audio.stream(text="akkam", language="om")
    assert audio.read() == b"RIFFwav"


# --- retries ---------------------------------------------------------------

def test_retries_once_on_500():
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        if state["n"] == 1:
            return json_response({"error": {"code": "x", "message": "boom"}}, status=500)
        return json_response({"status": "success", "data": {"translation": "ok", "source_language": "en", "target_language": "am", "quality": None}})

    addis, calls = client_with(handler)
    out = addis.translate.create(text="Hi", source="en", target="am")
    assert len(calls) == 2
    assert out["text"] == "ok"


def test_retries_twice_on_503_then_succeeds():
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        if state["n"] <= 2:
            return json_response({"error": {"code": "warming", "message": "warming up"}}, status=503)
        return json_response({"status": "success", "data": {"translation": "ok", "source_language": "en", "target_language": "am", "quality": None}})

    addis, calls = client_with(handler)
    out = addis.translate.create(text="Hi", source="en", target="am")
    assert len(calls) == 3  # default budget now 3
    assert out["text"] == "ok"
