"""Afaan Oromo (``language="om"``) on every Scribe entry point, and Amharic requests unchanged without it."""
import json
import time

import httpx
import pytest

import addisai.resources.scribe as scribe_module
from addisai import AddisAI, AddisAIError, APIError, ScribeLanguage  # noqa: F401  (exported alias)

OM = {"text": "Akkam jirtu", "request_id": "om1", "seconds": 2, "compute_ms": 5, "backend": "turbo", "chunk": "1120ms", "mode": "offline",
      "language": "om", "model": "addis-scribe-oromo-streaming",
      "usage": {"record_id": "ledger", "characters": 11, "price_per_1000_characters": 3.5, "credits_used": .0385, "credits_remaining": 9.96, "currency": "ETB", "settled": True}}
TICKET = {"token": "ephemeral", "request_id": "om1", "websocket_url": "wss://api.addisassistant.com/api/v1/scribe/stream", "backend": "turbo", "chunk": "320ms", "max_audio_seconds": 900}
QUEUED = {"request_id": "om1", "status": "queued", "poll_url": "/api/v1/scribe/requests/om1", "job_url": "/api/v1/scribe/jobs/om1"}


def recording(seen, response):
    def handler(request):
        seen.append(request)
        return response(request) if callable(response) else response
    return AddisAI(api_key="test-secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_transcribe_sends_language_om_as_a_query_parameter():
    seen = []
    result = recording(seen, httpx.Response(200, json={"data": OM})).scribe.transcribe(audio=b"audio", request_id="om1", language="om")
    assert dict(seen[0].url.params) == {"backend": "turbo", "chunk": "1120ms", "request_id": "om1", "language": "om", "stream": "false"}
    assert result["language"] == "om" and result["model"] == "addis-scribe-oromo-streaming"


def test_transcribe_without_language_sends_the_same_request_as_before():
    seen = []
    addis = recording(seen, httpx.Response(200, json={"data": {**OM, "language": "am", "model": "addis-scribe-streaming"}}))
    addis.scribe.transcribe(audio=b"audio", request_id="om1", timestamps="word", speakers=True)
    assert dict(seen[0].url.params) == {"backend": "turbo", "chunk": "1120ms", "request_id": "om1", "timestamps": "word", "speakers": "true", "stream": "false"}
    assert "language" not in str(seen[0].url)


def test_an_explicit_amharic_language_is_sent_as_given():
    seen = []
    recording(seen, httpx.Response(200, json={"data": OM})).scribe.transcribe(audio=b"audio", request_id="om1", language="am")
    assert seen[0].url.params["language"] == "am"


def test_stream_sends_language_only_when_set():
    seen = []
    addis = recording(seen, lambda r: httpx.Response(200, json={"data": OM}))
    with addis.scribe.stream(audio=b"audio", request_id="om1", language="om") as stream:
        assert stream.read()["language"] == "om"
    with addis.scribe.stream(audio=b"audio", request_id="om1") as stream:
        stream.read()
    assert dict(seen[0].url.params) == {"backend": "turbo", "chunk": "1120ms", "request_id": "om1", "language": "om", "stream": "true"}
    assert dict(seen[1].url.params) == {"backend": "turbo", "chunk": "1120ms", "request_id": "om1", "stream": "true"}


def test_live_session_sends_language_in_the_json_body_only_when_set():
    seen = []
    addis = recording(seen, httpx.Response(201, json={"data": TICKET}))
    addis.scribe.create_session(request_id="om1", language="om")
    addis.scribe.create_session(request_id="om1")
    assert json.loads(seen[0].content) == {"backend": "turbo", "chunk": "320ms", "request_id": "om1", "language": "om"}
    assert json.loads(seen[1].content) == {"backend": "turbo", "chunk": "320ms", "request_id": "om1"}
    assert not seen[0].url.params and not seen[1].url.params


def test_connect_passes_language_to_the_ticket():
    seen = []

    class Socket:
        def __init__(self): self.events = [{"type": "session.created", "sample_rate": 16000, "format": "pcm_s16le", "request_id": "om1"}]
        def send(self, text): pass
        def recv(self): return json.dumps(self.events.pop(0))
        def settimeout(self, value): pass
        def close(self): pass

    addis = recording(seen, httpx.Response(201, json={"data": TICKET}))
    with addis.scribe.connect(request_id="om1", language="om", websocket_factory=lambda url, **opts: Socket()) as live:
        assert live.session["type"] == "session.created"
    assert json.loads(seen[0].content)["language"] == "om"


def test_jobs_upload_and_transcribe_long_send_language_only_when_set(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    seen = []
    def respond(request):
        if request.method == "POST":
            return httpx.Response(202, json={"data": QUEUED})
        return httpx.Response(200, json={"data": {**OM, "mode": "job", "chunks": 1}})
    addis = recording(seen, respond)
    addis.scribe.jobs.upload(audio=b"audio", request_id="om1", language="om")
    addis.scribe.jobs.upload(audio=b"audio", request_id="om1")
    result = addis.scribe.transcribe_long(audio=b"audio", request_id="om1", language="om")
    posts = [dict(r.url.params) for r in seen if r.method == "POST"]
    base = {"request_id": "om1", "backend": "turbo", "chunk": "1120ms", "timestamps": "word"}
    assert posts == [{**base, "language": "om"}, base, {**base, "language": "om"}]
    assert result["language"] == "om" and result["model"] == "addis-scribe-oromo-streaming"


def test_job_declaration_sends_language_as_a_query_parameter_only_when_set(monkeypatch):
    monkeypatch.setattr(scribe_module, "MAX_UPLOAD_BYTES", 8)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    seen = []
    def respond(request):
        if request.method == "POST" and request.url.path == "/api/v1/scribe/jobs":
            return httpx.Response(201, json={"data": {"request_id": "om1", "status": "uploading", "part_bytes": 8, "parts": 2, "received": []}})
        if request.method == "PUT":
            return httpx.Response(200, json={"data": {"index": 0, "received": [0]}})
        if request.url.path.endswith("/complete"):
            return httpx.Response(202, json={"data": QUEUED})
        return httpx.Response(200, json={"data": {**OM, "mode": "job"}})
    addis = recording(seen, respond)
    addis.scribe.transcribe_long(audio=b"0123456789", request_id="om1", language="om")
    addis.scribe.jobs.create(request_id="om1", bytes=10)
    declarations = [r for r in seen if r.method == "POST" and r.url.path == "/api/v1/scribe/jobs"]
    body = {"request_id": "om1", "bytes": 10, "backend": "turbo", "chunk": "1120ms", "timestamps": "word", "speakers": False}
    assert [dict(r.url.params) for r in declarations] == [{"language": "om"}, {}]
    assert [json.loads(r.content) for r in declarations] == [body, body]
    # parts, complete and polling carry no language: the job remembers it
    assert all("language" not in str(r.url) for r in seen if r is not declarations[0])


def test_server_refusals_pass_through():
    seen = []
    refusal = httpx.Response(422, json={"error": {"code": "UNSUPPORTED_LANGUAGE", "message": "Use language=am|om|ti."}})
    with pytest.raises(APIError) as exc:
        recording(seen, refusal).scribe.transcribe(audio=b"audio", request_id="om1", language="xx")
    assert exc.value.status == 422 and exc.value.code == "UNSUPPORTED_LANGUAGE"
    assert seen[0].url.params["language"] == "xx"


def test_invalid_language_values_fail_locally_before_any_request():
    seen = []
    addis = recording(seen, httpx.Response(200, json={"data": OM}))
    for bad in ("", 1, True):
        with pytest.raises(AddisAIError, match="language"):
            addis.scribe.transcribe(audio=b"audio", language=bad)
        with pytest.raises(AddisAIError, match="language"):
            addis.scribe.create_session(language=bad)
        with pytest.raises(AddisAIError, match="language"):
            addis.scribe.jobs.upload(audio=b"audio", language=bad)
    assert seen == []
