import json
import struct

import httpx
import pytest

from addisai import AddisAI, AddisAIError, connect_realtime


def make_client(handler):
    return AddisAI(api_key="secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


class Pieces(httpx.SyncByteStream):
    def __init__(self, content):
        self.content = content

    def __iter__(self):
        for byte in self.content:
            yield bytes([byte])


def test_split_voice_frames_and_confirmation():
    content = struct.pack(">I", 3) + b"mp3" + b"\0\0\0\0" + b'{"data":{"id":"clip","usage":{"credits_used":1}}}'
    def handler(request):
        assert request.url.path == "/api/v1/voice/generations/stream"
        assert json.loads(request.content)["client_request_id"] == "stable"
        return httpx.Response(200, stream=Pieces(content), headers={"X-Addis-Audio-Protocol": "mp3-frames-v1"})
    stream = make_client(handler).voice.stream(voice_id="am-loza", language="am", text="A complete sentence.", client_request_id="stable")
    assert stream.read() == b"mp3"
    assert stream.metadata["usage"]["credits_used"] == 1
    assert stream.client_request_id == "stable"


def test_truncated_voice_stream_is_an_error():
    stream = make_client(lambda r: httpx.Response(200, content=struct.pack(">I", 3) + b"mp3", headers={"X-Addis-Audio-Protocol": "mp3-frames-v1"})).voice.stream(voice_id="am-loza", language="am", text="A complete sentence.")
    with pytest.raises(AddisAIError, match="billing confirmation"):
        stream.read()


def test_voice_replay_downloads_saved_clip():
    def handler(request):
        if request.url.path.endswith("/stream"):
            return httpx.Response(201, json={"data": {"id": "clip", "audio_url": "https://cdn.addisassistant.com/audio/clips/clip.mp3?token=scoped"}})
        assert "x-api-key" not in request.headers
        return httpx.Response(200, content=b"saved-audio")
    stream = make_client(handler).voice.stream(voice_id="am-loza", language="am", text="A complete sentence.")
    assert stream.read() == b"saved-audio"


class Socket:
    def __init__(self):
        self.sent = []
        self.events = [{"type": "session.created", "session_id": "session"}]
        self.closed = False

    def send(self, value):
        event = json.loads(value)
        self.sent.append(event)
        if event["type"] == "speech.create":
            self.events.extend([
                {"type": "speech.started", "request_id": event["request_id"]},
                {"type": "audio.delta", "request_id": event["request_id"], "sequence": 0, "format": "mp3", "audio": "bXAz"},
                {"type": "speech.completed", "request_id": event["request_id"], "data": {"id": "clip"}},
            ])

    def recv(self):
        return json.dumps(self.events.pop(0))

    def settimeout(self, value):
        pass

    def close(self):
        self.closed = True


def test_ticket_socket_and_repeated_turns():
    socket = Socket()
    with connect_realtime({"token": "ephemeral", "websocket_url": "wss://api.addisassistant.com/api/v1/realtime/voice"}, websocket_factory=lambda url, **opts: socket) as connection:
        assert b"".join(connection.speak("A complete sentence.", "turn-1")) == b"mp3"
        assert b"".join(connection.speak("Another sentence.", "turn-2")) == b"mp3"
        assert connection.last_completion["id"] == "clip"
        assert socket.sent[0] == {"type": "session.authenticate", "token": "ephemeral"}
    assert socket.closed


def test_session_serialization():
    def handler(request):
        assert request.headers["x-api-key"] == "secret"
        assert json.loads(request.content) == {"voice_id": "am-loza", "language": "am", "audio_format": "mp3", "max_text_characters": 100}
        return httpx.Response(201, json={"data": {"token": "ephemeral"}})
    assert make_client(handler).realtime.create_session(voice_id="am-loza", language="am", max_text_characters=100)["token"] == "ephemeral"


def test_query_credentials_rejected():
    with pytest.raises(AddisAIError, match="without credentials"):
        connect_realtime({"token": "secret", "websocket_url": "wss://api.addisassistant.com/api/v1/realtime/voice?token=secret"})
