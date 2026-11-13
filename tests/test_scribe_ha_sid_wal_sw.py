"""Hausa, Sidama, Wolaytta and Swahili on every Scribe entry point, sent exactly like Afaan Oromo and Tigrinya."""
import json
import time
import typing

import httpx
import pytest

import addisai.resources.scribe as scribe_module
from addisai import AddisAI, ScribeLanguage

MODELS = {
    "ha": ("addis-scribe-hausa-streaming", "sannu da zuwa"),
    "sid": ("addis-scribe-sidama-streaming", "sidaamu afoo"),
    "wal": ("addis-scribe-wolaytta-streaming", "wolaytta doonaa"),
    "sw": ("addis-scribe-swahili-streaming", "Habari za asubuhi."),
}
LANGUAGES = pytest.mark.parametrize("code", list(MODELS))


def result(code, **extra):
    model, text = MODELS[code]
    return {"text": text, "request_id": f"{code}1", "seconds": 2, "compute_ms": 5, "backend": "turbo", "chunk": "1120ms",
            "mode": "offline", "language": code, "model": model,
            "usage": {"record_id": "ledger", "characters": len(text), "price_per_1000_characters": 3.5, "credits_used": .05,
                      "credits_remaining": 9.95, "currency": "ETB", "settled": True}, **extra}


def recording(seen, response):
    def handler(request):
        seen.append(request)
        return response(request) if callable(response) else response
    return AddisAI(api_key="test-secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_scribe_language_alias_lists_every_scribe_language():
    assert typing.get_args(ScribeLanguage) == ("am", "om", "ti", "ha", "sid", "wal", "sw", "en")


@LANGUAGES
def test_transcribe_sends_the_language_as_a_query_parameter(code):
    seen = []
    out = recording(seen, httpx.Response(200, json={"data": result(code)})).scribe.transcribe(
        audio=b"audio", request_id=f"{code}1", language=code)
    assert dict(seen[0].url.params) == {"backend": "turbo", "chunk": "1120ms", "request_id": f"{code}1", "language": code,
                                        "stream": "false"}
    assert out["language"] == code and out["model"] == MODELS[code][0]


@pytest.mark.parametrize("code", ["ha", "sid", "wal"])
def test_transcribe_with_captions_and_speakers_keeps_the_language(code):
    seen = []
    recording(seen, httpx.Response(200, json={"data": result(code)})).scribe.transcribe(
        audio=b"audio", request_id=f"{code}1", language=code, timestamps="word", speakers=True)
    assert dict(seen[0].url.params) == {"backend": "turbo", "chunk": "1120ms", "request_id": f"{code}1", "timestamps": "word",
                                        "speakers": "true", "language": code, "stream": "false"}


def test_swahili_captions_keep_the_language():
    seen = []
    recording(seen, httpx.Response(200, json={"data": result("sw")})).scribe.transcribe(
        audio=b"audio", request_id="sw1", language="sw", timestamps="word")
    assert dict(seen[0].url.params) == {"backend": "turbo", "chunk": "1120ms", "request_id": "sw1", "timestamps": "word",
                                        "language": "sw", "stream": "false"}


@LANGUAGES
def test_stream_sends_the_language(code):
    seen = []
    addis = recording(seen, lambda r: httpx.Response(200, json={"data": result(code)}))
    with addis.scribe.stream(audio=b"audio", request_id=f"{code}1", language=code) as stream:
        assert stream.read()["language"] == code
    assert dict(seen[0].url.params) == {"backend": "turbo", "chunk": "1120ms", "request_id": f"{code}1", "language": code,
                                        "stream": "true"}


@LANGUAGES
def test_live_session_sends_the_language_in_the_json_body(code):
    seen = []
    ticket = {"token": "ephemeral", "request_id": f"{code}1", "websocket_url": "wss://api.addisassistant.com/api/v1/scribe/stream",
              "backend": "turbo", "chunk": "320ms", "max_audio_seconds": 900}
    recording(seen, httpx.Response(201, json={"data": ticket})).scribe.create_session(request_id=f"{code}1", language=code)
    assert json.loads(seen[0].content) == {"backend": "turbo", "chunk": "320ms", "request_id": f"{code}1", "language": code}
    assert not seen[0].url.params


@LANGUAGES
def test_connect_passes_the_language_to_the_ticket(code):
    seen = []
    ticket = {"token": "ephemeral", "request_id": f"{code}1", "websocket_url": "wss://api.addisassistant.com/api/v1/scribe/stream",
              "backend": "turbo", "chunk": "320ms", "max_audio_seconds": 900}

    class Socket:
        def __init__(self): self.events = [{"type": "session.created", "sample_rate": 16000, "format": "pcm_s16le", "request_id": f"{code}1"}]
        def send(self, text): pass
        def recv(self): return json.dumps(self.events.pop(0))
        def settimeout(self, value): pass
        def close(self): pass

    addis = recording(seen, httpx.Response(201, json={"data": ticket}))
    with addis.scribe.connect(request_id=f"{code}1", language=code, websocket_factory=lambda url, **opts: Socket()) as live:
        assert live.session["type"] == "session.created"
    assert json.loads(seen[0].content)["language"] == code


@LANGUAGES
def test_jobs_upload_and_transcribe_long_send_the_language(code, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    seen = []
    queued = {"request_id": f"{code}1", "status": "queued", "poll_url": f"/api/v1/scribe/requests/{code}1",
              "job_url": f"/api/v1/scribe/jobs/{code}1"}

    def respond(request):
        if request.method == "POST":
            return httpx.Response(202, json={"data": queued})
        return httpx.Response(200, json={"data": result(code, mode="job", chunks=1)})
    addis = recording(seen, respond)
    addis.scribe.jobs.upload(audio=b"audio", request_id=f"{code}1", language=code)
    out = addis.scribe.transcribe_long(audio=b"audio", request_id=f"{code}1", language=code)
    posts = [dict(r.url.params) for r in seen if r.method == "POST"]
    base = {"request_id": f"{code}1", "backend": "turbo", "chunk": "1120ms", "timestamps": "word"}
    assert posts == [{**base, "language": code}, {**base, "language": code}]
    assert out["language"] == code and out["model"] == MODELS[code][0]


@LANGUAGES
def test_job_declaration_sends_the_language_as_a_query_parameter_only(code, monkeypatch):
    monkeypatch.setattr(scribe_module, "MAX_UPLOAD_BYTES", 8)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    seen = []
    queued = {"request_id": f"{code}1", "status": "queued", "poll_url": f"/api/v1/scribe/requests/{code}1",
              "job_url": f"/api/v1/scribe/jobs/{code}1"}

    def respond(request):
        if request.method == "POST" and request.url.path == "/api/v1/scribe/jobs":
            return httpx.Response(201, json={"data": {"request_id": f"{code}1", "status": "uploading", "part_bytes": 8, "parts": 2,
                                                      "received": []}})
        if request.method == "PUT":
            return httpx.Response(200, json={"data": {"index": 0, "received": [0]}})
        if request.url.path.endswith("/complete"):
            return httpx.Response(202, json={"data": queued})
        return httpx.Response(200, json={"data": result(code, mode="job")})
    addis = recording(seen, respond)
    addis.scribe.transcribe_long(audio=b"0123456789", request_id=f"{code}1", language=code)
    addis.scribe.jobs.create(request_id=f"{code}1", bytes=10, language=code)
    declarations = [r for r in seen if r.method == "POST" and r.url.path == "/api/v1/scribe/jobs"]
    body = {"request_id": f"{code}1", "bytes": 10, "backend": "turbo", "chunk": "1120ms", "timestamps": "word", "speakers": False}
    assert [dict(r.url.params) for r in declarations] == [{"language": code}, {"language": code}]
    assert [json.loads(r.content) for r in declarations] == [body, body]
    # parts, complete and polling carry no language: the job remembers it
    assert all("language" not in str(r.url) for r in seen if r not in declarations)
