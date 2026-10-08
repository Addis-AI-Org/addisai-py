import json
import httpx
import pytest
from addisai import AddisAI, AddisAIError, connect_scribe

RAW = {"text": "ሰላም😀", "request_id": "stable", "seconds": 1, "compute_ms": 5, "backend": "standard", "chunk": "1120ms", "mode": "offline", "model": "addis-scribe-streaming", "usage": {"record_id": "ledger", "characters": 6, "price_per_1000_characters": 3.5, "credits_used": .021, "credits_remaining": 9.979, "currency": "ETB", "settled": True}}
TICKET = {"token": "ephemeral", "request_id": "stable", "websocket_url": "wss://api.addisassistant.com/api/v1/scribe/stream", "backend": "standard", "chunk": "320ms", "max_audio_seconds": 180}

def client(handler):
    return AddisAI(api_key="test-secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

class Pieces(httpx.SyncByteStream):
    def __init__(self, content): self.content = content
    def __iter__(self):
        for byte in self.content: yield bytes([byte])

def ndjson(events):
    content = "\n".join(json.dumps(e, ensure_ascii=False) for e in events).encode()
    return httpx.Response(200, stream=Pieces(content), headers={"content-type": "application/x-ndjson"})

def test_multipart_parameters_auth_and_settled_usage():
    def handler(request):
        assert request.url.path == "/api/v1/scribe/transcribe"
        assert request.url.params["request_id"] == "stable"
        assert request.url.params["stream"] == "false"
        assert request.headers["x-api-key"] == "test-secret"
        assert request.headers["content-type"].startswith("multipart/form-data;")
        assert b'name="audio"' in request.content
        return httpx.Response(200, json={"data": RAW})
    result = client(handler).scribe.transcribe(audio=b"audio", request_id="stable")
    assert result["text"] == RAW["text"]
    assert result["usage"]["credits_used"] == .021

def test_paid_upload_and_session_issuance_are_not_retried():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"code": "BILLING_PENDING", "message": "recover"}})
    addis = client(handler)
    with pytest.raises(AddisAIError, match="recover"):
        addis.scribe.transcribe(audio=b"audio", request_id="stable", request_options={"max_retries": 3})
    with pytest.raises(AddisAIError, match="recover"):
        addis.scribe.create_session(request_id="stable", request_options={"max_retries": 3})
    assert len(calls) == 2

def test_split_utf8_and_completion_without_newline():
    def handler(request):
        assert request.url.params["stream"] == "true"
        assert b'name="audio"' in request.content
        return ndjson([{"type": "transcript.partial", "text": "ሰላ", "request_id": "stable"}, {"type": "transcript.completed", "data": RAW}])
    with client(handler).scribe.stream(audio=b"audio", request_id="stable") as stream:
        events = list(stream)
        assert [e["type"] for e in events] == ["transcript.partial", "transcript.completed"]
        assert stream.request_id == "stable"
        assert stream.completion["usage"]["settled"] is True

def test_stream_handles_already_paid_json_replay():
    with client(lambda r: httpx.Response(200, json={"data": {**RAW, "idempotent_replay": True}})).scribe.stream(audio=b"audio", request_id="stable") as stream:
        assert stream.read()["idempotent_replay"] is True

@pytest.mark.parametrize("events", [[{"type": "transcript.partial", "text": "ሰላ"}], [{"type": "transcript.completed", "data": {**RAW, "usage": {"settled": False}}}]])
def test_incomplete_or_unsettled_streams_are_rejected(events):
    with client(lambda r: ndjson(events)).scribe.stream(audio=b"audio") as stream:
        with pytest.raises(AddisAIError, match="billing"):
            stream.read()

def test_stream_preserves_api_error_status_and_code():
    with client(lambda r: ndjson([{"type": "error", "status": 429, "error": {"code": "BUSY", "message": "busy"}}])).scribe.stream(audio=b"audio") as stream:
        with pytest.raises(AddisAIError) as exc:
            stream.read()
        assert exc.value.status == 429
        assert exc.value.code == "BUSY"

def test_validation_and_recovery_do_not_upload_or_regenerate_audio():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.path == "/api/v1/scribe/requests/stable"
        assert request.method == "GET"
        return httpx.Response(200, json={"data": {**RAW, "idempotent_replay": True}})
    addis = client(handler)
    with pytest.raises(AddisAIError): addis.scribe.create_session(request_id="bad/id")
    with pytest.raises(AddisAIError): addis.scribe.transcribe(audio=b"")
    assert len(calls) == 0
    assert addis.scribe.recover("stable")["idempotent_replay"] is True
    assert len(calls) == 1

def test_session_defaults_capabilities_and_wallet_usage():
    def handler(request):
        if request.url.path.endswith("/sessions"):
            assert json.loads(request.content) == {"backend": "standard", "chunk": "320ms", "request_id": "stable"}
            return httpx.Response(201, json={"data": TICKET})
        if request.url.path.endswith("/usage"):
            return httpx.Response(200, json={"data": {"balance": 10, "pricing": {"price_per_1000_characters": 3.5}}})
        return httpx.Response(200, json={"data": {"language": "am", "max_audio_seconds": 180}})
    addis = client(handler)
    assert addis.scribe.capabilities()["language"] == "am"
    assert addis.scribe.usage()["pricing"]["price_per_1000_characters"] == 3.5
    assert addis.scribe.create_session(request_id="stable")["request_id"] == "stable"

class Socket:
    def __init__(self, replay=False):
        self.sent = []; self.binary = []; self.closed = False
        self.events = [{"type": "transcript.completed", "data": {**RAW, "idempotent_replay": True}}] if replay else [{"type": "session.created", "sample_rate": 16000, "format": "pcm_s16le", "request_id": "stable"}]
    def send(self, text):
        event = json.loads(text); self.sent.append(event)
        if event["type"] == "audio.finish": self.events.append({"type": "transcript.completed", "data": RAW})
    def send_binary(self, audio):
        self.binary.append(audio); self.events.append({"type": "transcript.partial", "text": "ሰላ", "request_id": "stable"})
    def recv(self): return json.dumps(self.events.pop(0)) if self.events else ""
    def settimeout(self, value): pass
    def close(self): self.closed = True

def test_ticket_first_binary_pcm_and_settled_completion():
    socket = Socket()
    with connect_scribe(TICKET, websocket_factory=lambda url, **opts: socket) as live:
        live.send_audio(b"\0" * 6400); live.finish()
        assert [e["type"] for e in live] == ["session.created", "transcript.partial", "transcript.completed"]
        assert live.completion["usage"]["settled"] is True
        assert socket.sent[0] == {"type": "session.authenticate", "token": "ephemeral"}
        assert socket.binary == [b"\0" * 6400]
    assert socket.closed

def test_completed_microphone_replay_needs_no_session_created_or_audio():
    socket = Socket(replay=True)
    with connect_scribe(TICKET, websocket_factory=lambda url, **opts: socket) as live:
        assert live.completion["idempotent_replay"] is True
        assert [e["type"] for e in live] == ["transcript.completed"]
        assert len(socket.sent) == 1
        assert socket.binary == []

def test_socket_url_credentials_and_invalid_pcm_are_rejected():
    with pytest.raises(AddisAIError, match="without credentials"):
        connect_scribe({**TICKET, "websocket_url": TICKET["websocket_url"] + "?token=secret"})
    with connect_scribe(TICKET, websocket_factory=lambda url, **opts: Socket()) as live:
        with pytest.raises(AddisAIError, match="PCM16"): live.send_audio(b"123")

def test_interrupted_socket_is_not_success():
    with connect_scribe(TICKET, websocket_factory=lambda url, **opts: Socket()) as live:
        with pytest.raises(AddisAIError, match="billing confirmation"):
            list(live)
