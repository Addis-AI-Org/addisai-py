"""Developer WebSocket sessions. API keys stay on the application server."""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, Iterator, Optional
from urllib.parse import urlsplit

from .._exceptions import AddisAIError
from .._idempotency import ulid
from .._transport import Options, Transport, unwrap_data


class Realtime:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def create_session(self, *, voice_id: str, language: str, audio_format: str = "mp3",
                       max_text_characters: int = 5000, request_options: Optional[Options] = None) -> Dict[str, Any]:
        """Create a voice-scoped, one-use ticket valid for 60 seconds."""
        return unwrap_data(self._transport.request("POST", "/api/v1/realtime/sessions",
                           json={"voice_id": voice_id, "language": language, "audio_format": audio_format,
                                 "max_text_characters": max_text_characters},
                           options={"max_retries": 0, **(request_options or {})}))

    def connect(self, *, voice_id: str, language: str, audio_format: str = "mp3",
                max_text_characters: int = 5000, request_options: Optional[Options] = None,
                websocket_factory=None) -> "RealtimeConnection":
        """Create a ticket and open its socket. Install ``addisai[realtime]``."""
        session = self.create_session(voice_id=voice_id, language=language, audio_format=audio_format,
                                      max_text_characters=max_text_characters, request_options=request_options)
        return connect_realtime(session, websocket_factory=websocket_factory)


def connect_realtime(session: Dict[str, Any], *, websocket_factory=None) -> "RealtimeConnection":
    """Connect with only a scoped ticket; no developer key is sent to the socket."""
    url = session["websocket_url"]
    parsed = urlsplit(url)
    if (parsed.username or parsed.password or parsed.query or parsed.fragment or
            (parsed.scheme != "wss" and not (parsed.scheme == "ws" and parsed.hostname in ("localhost", "127.0.0.1")))):
        raise AddisAIError("Realtime WebSocket URL must use wss without credentials or query parameters.")
    if websocket_factory is None:
        try:
            from websocket import create_connection
        except ImportError:
            raise AddisAIError('Install WebSocket support with: pip install "addisai[realtime]"') from None
        websocket_factory = create_connection
    socket = websocket_factory(url, timeout=10)
    try:
        socket.send(json.dumps({"type": "session.authenticate", "token": session["token"]}))
        connection = RealtimeConnection(socket)
        event = connection.receive()
        if event.get("type") != "session.created":
            raise AddisAIError("Realtime session was rejected or expired.")
        socket.settimeout(220)
        connection.session = event
        return connection
    except Exception:
        socket.close()
        raise


class RealtimeConnection:
    def __init__(self, socket) -> None:
        self._socket = socket
        self._closed = False
        self.session: Optional[Dict[str, Any]] = None
        self.last_completion: Optional[Dict[str, Any]] = None

    def send(self, event: Dict[str, Any]) -> None:
        if self._closed:
            raise AddisAIError("Realtime connection is closed.")
        self._socket.send(json.dumps(event))

    def receive(self) -> Dict[str, Any]:
        message = self._socket.recv()
        if not message:
            raise AddisAIError("Realtime connection closed before completion.")
        if len(message) > 3 * 1024 * 1024:
            self.close()
            raise AddisAIError("Realtime event exceeds the limit.")
        try:
            event = json.loads(message)
        except ValueError:
            raise AddisAIError("Invalid realtime event.") from None
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise AddisAIError("Invalid realtime event.")
        if event["type"] in ("speech.completed", "speech.cancelled"):
            self.last_completion = event["data"]
        return event

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        while not self._closed:
            yield self.receive()

    def append(self, text: str) -> None:
        self.send({"type": "text.append", "text": text})

    def commit(self, request_id: Optional[str] = None) -> str:
        rid = request_id or ulid()
        self.send({"type": "text.commit", "request_id": rid})
        return rid

    def cancel(self) -> None:
        """Stop audio delivery. A started generation still completes and is billed."""
        self.send({"type": "speech.cancel"})

    def speak(self, text: str, request_id: Optional[str] = None) -> Iterator[bytes]:
        """Yield one MP3 turn; consume fully to receive clip and billing metadata."""
        rid = request_id or ulid()
        self.send({"type": "speech.create", "text": text, "request_id": rid})
        for event in self:
            if event["type"] == "error" and event.get("request_id") in (None, rid):
                raise AddisAIError("{code}: {message}".format(**event["error"]))
            if event.get("request_id") != rid:
                continue
            if event["type"] == "audio.delta":
                if event["format"] != "mp3":
                    raise AddisAIError("speak requires an mp3 session. Consume audio.delta events to play mixed WAV/MP3.")
                yield decode_realtime_audio(event)
            if event["type"] in ("speech.completed", "speech.cancelled"):
                return
        raise AddisAIError("Realtime speech ended before completion.")

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._socket.close()

    def __enter__(self) -> "RealtimeConnection":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def decode_realtime_audio(event: Dict[str, Any]) -> bytes:
    return base64.b64decode(event["audio"], validate=True)
