"""Tigrinya (``language="ti"``) on every Scribe entry point, sent exactly like Afaan Oromo."""
import json
import time
import typing

import httpx

import addisai.resources.scribe as scribe_module
from addisai import AddisAI, ScribeLanguage

TI = {"text": "ሰላም ከመይ ኣለኻ", "request_id": "ti1", "seconds": 2, "compute_ms": 5, "backend": "turbo", "chunk": "1120ms", "mode": "offline",
      "language": "ti", "model": "addis-scribe-tigrinya-streaming",
      "usage": {"record_id": "ledger", "characters": 11, "price_per_1000_characters": 3.5, "credits_used": .0385, "credits_remaining": 9.96, "currency": "ETB", "settled": True}}
TICKET = {"token": "ephemeral", "request_id": "ti1", "websocket_url": "wss://api.addisassistant.com/api/v1/scribe/stream", "backend": "turbo", "chunk": "320ms", "max_audio_seconds": 900}
QUEUED = {"request_id": "ti1", "status": "queued", "poll_url": "/api/v1/scribe/requests/ti1", "job_url": "/api/v1/scribe/jobs/ti1"}


def recording(seen, response):
    def handler(request):
        seen.append(request)
        return response(request) if callable(response) else response
    return AddisAI(api_key="test-secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_scribe_language_alias_includes_tigrinya():
    assert typing.get_args(ScribeLanguage) == ("am", "om", "ti")


def test_transcribe_sends_language_ti_as_a_query_parameter():
    seen = []
    result = recording(seen, httpx.Response(200, json={"data": TI})).scribe.transcribe(audio=b"audio", request_id="ti1", language="ti")
    assert dict(seen[0].url.params) == {"backend": "turbo", "chunk": "1120ms", "request_id": "ti1", "language": "ti", "stream": "false"}
    assert result["language"] == "ti" and result["model"] == "addis-scribe-tigrinya-streaming"


def test_transcribe_with_captions_and_speakers_keeps_language_ti():
    seen = []
    recording(seen, httpx.Response(200, json={"data": TI})).scribe.transcribe(
        audio=b"audio", request_id="ti1", language="ti", timestamps="word", speakers=True)
    assert dict(seen[0].url.params) == {"backend": "turbo", "chunk": "1120ms", "request_id": "ti1", "timestamps": "word",
                                        "speakers": "true", "language": "ti", "stream": "false"}


def test_stream_sends_language_ti():
    seen = []
    addis = recording(seen, lambda r: httpx.Response(200, json={"data": TI}))
    with addis.scribe.stream(audio=b"audio", request_id="ti1", language="ti") as stream:
        assert stream.read()["language"] == "ti"
    assert dict(seen[0].url.params) == {"backend": "turbo", "chunk": "1120ms", "request_id": "ti1", "language": "ti", "stream": "true"}


def test_live_session_sends_language_ti_in_the_json_body():
    seen = []
    recording(seen, httpx.Response(201, json={"data": TICKET})).scribe.create_session(request_id="ti1", language="ti")
    assert json.loads(seen[0].content) == {"backend": "turbo", "chunk": "320ms", "request_id": "ti1", "language": "ti"}
    assert not seen[0].url.params


def test_connect_passes_language_ti_to_the_ticket():
    seen = []

    class Socket:
        def __init__(self): self.events = [{"type": "session.created", "sample_rate": 16000, "format": "pcm_s16le", "request_id": "ti1"}]
        def send(self, text): pass
        def recv(self): return json.dumps(self.events.pop(0))
        def settimeout(self, value): pass
        def close(self): pass

    addis = recording(seen, httpx.Response(201, json={"data": TICKET}))
    with addis.scribe.connect(request_id="ti1", language="ti", websocket_factory=lambda url, **opts: Socket()) as live:
        assert live.session["type"] == "session.created"
    assert json.loads(seen[0].content)["language"] == "ti"


def test_jobs_upload_and_transcribe_long_send_language_ti(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    seen = []
    def respond(request):
        if request.method == "POST":
            return httpx.Response(202, json={"data": QUEUED})
        return httpx.Response(200, json={"data": {**TI, "mode": "job", "chunks": 1}})
    addis = recording(seen, respond)
    addis.scribe.jobs.upload(audio=b"audio", request_id="ti1", language="ti")
    result = addis.scribe.transcribe_long(audio=b"audio", request_id="ti1", language="ti")
    posts = [dict(r.url.params) for r in seen if r.method == "POST"]
    base = {"request_id": "ti1", "backend": "turbo", "chunk": "1120ms", "timestamps": "word"}
    assert posts == [{**base, "language": "ti"}, {**base, "language": "ti"}]
    assert result["language"] == "ti" and result["model"] == "addis-scribe-tigrinya-streaming"


def test_job_declaration_sends_language_ti_as_a_query_parameter_only(monkeypatch):
    monkeypatch.setattr(scribe_module, "MAX_UPLOAD_BYTES", 8)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    seen = []
    def respond(request):
        if request.method == "POST" and request.url.path == "/api/v1/scribe/jobs":
            return httpx.Response(201, json={"data": {"request_id": "ti1", "status": "uploading", "part_bytes": 8, "parts": 2, "received": []}})
        if request.method == "PUT":
            return httpx.Response(200, json={"data": {"index": 0, "received": [0]}})
        if request.url.path.endswith("/complete"):
            return httpx.Response(202, json={"data": QUEUED})
        return httpx.Response(200, json={"data": {**TI, "mode": "job"}})
    addis = recording(seen, respond)
    addis.scribe.transcribe_long(audio=b"0123456789", request_id="ti1", language="ti")
    addis.scribe.jobs.create(request_id="ti1", bytes=10, language="ti")
    declarations = [r for r in seen if r.method == "POST" and r.url.path == "/api/v1/scribe/jobs"]
    body = {"request_id": "ti1", "bytes": 10, "backend": "turbo", "chunk": "1120ms", "timestamps": "word", "speakers": False}
    assert [dict(r.url.params) for r in declarations] == [{"language": "ti"}, {"language": "ti"}]
    assert [json.loads(r.content) for r in declarations] == [body, body]
    # parts, complete and polling carry no language: the job remembers it
    assert all("language" not in str(r.url) for r in seen if r not in declarations)
