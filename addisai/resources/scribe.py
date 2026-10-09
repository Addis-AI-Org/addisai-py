"""Amharic Scribe transcription. Account credentials stay on the application server."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterator, Optional
from urllib.parse import urlsplit

from .._exceptions import AddisAIError, make_api_error
from .._idempotency import ulid
from .._transport import Options, Transport, _to_error, unwrap_data
from .speech import AudioInput

PATH = "/api/v1/scribe"
MAX_EVENT = 512 * 1024
BACKENDS = ("standard", "turbo")
TIMESTAMPS = ("none", "word")


def _params(backend, chunk, request_id):
    if backend not in BACKENDS or chunk not in ("320ms", "1120ms"):
        raise AddisAIError("Invalid Scribe backend or chunk.")
    rid = ulid() if request_id is None else request_id
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", rid):
        raise AddisAIError("Scribe request_id must contain 1–128 letters, digits, underscores or hyphens.")
    return {"backend": backend, "chunk": chunk, "request_id": rid}


def _timestamps(value):
    """Validate ``timestamps``; only a non-default value reaches the wire."""
    if value not in TIMESTAMPS:
        raise AddisAIError('Scribe timestamps must be "none" or "word".')
    return {} if value == "none" else {"timestamps": value}


def _speakers(value, backend):
    """Validate ``speakers``; only ``True`` reaches the wire, and it needs the turbo backend."""
    if not isinstance(value, bool):
        raise AddisAIError("Scribe speakers must be True or False.")
    if not value:
        return {}
    if backend != "turbo":
        raise AddisAIError('Scribe speaker labels are available on the turbo backend; '
                           'pass backend="turbo" with speakers=True.')
    return {"speakers": "true"}


def _completion(data):
    if not isinstance(data, dict) or not isinstance(data.get("text"), str) or data.get("usage", {}).get("settled") is not True:
        raise AddisAIError("Scribe ended without settled billing. Recover the same request_id before retrying.")
    return data


def _event(value):
    if not isinstance(value, dict):
        raise AddisAIError("Invalid Scribe event.")
    kind = value.get("type")
    if kind == "error":
        raise make_api_error(value.get("status", 503), value, "", {})
    if kind == "transcript.completed":
        _completion(value.get("data"))
    elif kind == "transcript.partial" and isinstance(value.get("text"), str):
        pass
    elif kind == "session.created" and value.get("sample_rate") == 16000 and value.get("format") == "pcm_s16le":
        pass
    else:
        raise AddisAIError("Invalid Scribe event.")
    return value


def _parse(text):
    try:
        value = json.loads(text)
    except ValueError:
        raise AddisAIError("Invalid Scribe JSON event.") from None
    return _event(value)


def _files(audio):
    if isinstance(audio, tuple):
        part = audio
    elif isinstance(audio, (bytes, bytearray)):
        if not audio or len(audio) > 25 * 1024**2:
            raise AddisAIError("Scribe audio must contain 1 byte to 25 MiB.")
        part = ("audio.wav", bytes(audio), "audio/wav")
    else:
        part = ("audio.wav", audio, "audio/wav")
    return {"audio": part}


class Scribe:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def capabilities(self, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        return unwrap_data(self._transport.request("GET", PATH, options=request_options))

    def usage(self, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        return unwrap_data(self._transport.request("GET", PATH + "/usage", options=request_options))

    def recover(self, request_id: str, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        _params("standard", "1120ms", request_id)
        return _completion(unwrap_data(self._transport.request("GET", PATH + "/requests/" + request_id,
                           options={**(request_options or {}), "max_retries": 0})))

    def transcribe(self, *, audio: AudioInput, backend: str = "standard", chunk: str = "1120ms",
                   request_id: Optional[str] = None, timestamps: str = "none", speakers: bool = False,
                   request_options: Optional[Options] = None) -> Dict[str, Any]:
        """Transcribe an Amharic file. No automatic retries; recover its request_id after interruptions.

        ``backend`` is ``"standard"`` (default) or ``"turbo"``. ``timestamps="word"`` adds ``words``
        and caption ``segments`` to the result (default ``"none"``, which sends no ``timestamps`` parameter).
        ``speakers=True`` (turbo only; default ``False``, which sends no ``speakers`` parameter) turns on
        word timestamps and adds a ``speaker`` number (or ``None``) to every word and segment, plus a
        ``speakers`` count to the result.
        """
        params = {**_params(backend, chunk, request_id), **_timestamps(timestamps), **_speakers(speakers, backend)}
        return _completion(unwrap_data(self._transport.request("POST", PATH + "/transcribe",
                           query={**params, "stream": "false"}, files=_files(audio), timeout_floor=600,
                           options={**(request_options or {}), "max_retries": 0})))

    def stream(self, *, audio: AudioInput, backend: str = "standard", chunk: str = "1120ms",
               request_id: Optional[str] = None, timestamps: str = "none", speakers: bool = False,
               request_options: Optional[Options] = None) -> "ScribeTranscriptStream":
        """Upload a file, then iterate partials and settled completion. Use as a context manager.

        ``backend`` defaults to ``"standard"``. Word timestamps and speaker labels are not available here;
        use transcribe().
        """
        if speakers is True:
            raise AddisAIError('Scribe speaker labels are available only for completed uploads; '
                               'use transcribe(backend="turbo", speakers=True) instead of stream().')
        _speakers(speakers, "turbo")
        if _timestamps(timestamps).get("timestamps") == "word":
            raise AddisAIError('Scribe timestamps are available only for completed uploads; '
                               'use transcribe(timestamps="word") instead of stream().')
        params = _params(backend, chunk, request_id)
        context = self._transport.stream("POST", PATH + "/transcribe", query={**params, "stream": "true"},
                                        files=_files(audio), options={"timeout": 600, **(request_options or {})})
        return ScribeTranscriptStream(context, params["request_id"])

    def create_session(self, *, backend: str = "standard", chunk: str = "320ms", request_id: Optional[str] = None,
                       request_options: Optional[Options] = None) -> Dict[str, Any]:
        """Create a one-use ticket on your server, with no automatic issuance retries."""
        return unwrap_data(self._transport.request("POST", PATH + "/sessions", json=_params(backend, chunk, request_id),
                          options={**(request_options or {}), "max_retries": 0}))

    def connect(self, *, backend: str = "standard", chunk: str = "320ms", request_id: Optional[str] = None,
                request_options: Optional[Options] = None, websocket_factory=None) -> "ScribeConnection":
        session = self.create_session(backend=backend, chunk=chunk, request_id=request_id, request_options=request_options)
        return connect_scribe(session, websocket_factory=websocket_factory)


class ScribeTranscriptStream:
    def __init__(self, context, request_id: str):
        self.request_id = request_id
        self.completion: Optional[Dict[str, Any]] = None
        self._context = context
        self._response = None
        self._consumed = False

    def __enter__(self):
        self._open()
        return self

    def _open(self):
        if self._response is None:
            self._response = self._context.__enter__()
            if not self._response.is_success:
                self._response.read()
                error = _to_error(self._response)
                self.close()
                raise error
        return self._response

    def __exit__(self, *args):
        self.close()

    def close(self):
        """Stops reading; accepted audio may still be transcribed and billed. Use recover()."""
        if self._response is not None:
            self._context.__exit__(None, None, None)
            self._response = None

    def read(self) -> Dict[str, Any]:
        for _ in self:
            pass
        return self.completion

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        if self._consumed:
            raise AddisAIError("A Scribe stream can only be consumed once.")
        self._consumed = True
        response = self._open()
        try:
            if "application/json" in response.headers.get("content-type", ""):
                response.read()
                self.completion = _completion(unwrap_data(response.json()))
                yield {"type": "transcript.completed", "data": self.completion}
                return
            pending = b""
            for piece in response.iter_bytes():
                pending += piece
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    if len(line) > MAX_EVENT:
                        raise AddisAIError("Scribe event exceeds the limit.")
                    if not line.strip():
                        continue
                    event = _parse(line.decode("utf-8"))
                    if event["type"] == "transcript.completed":
                        self.completion = event["data"]
                    yield event
                    if self.completion is not None:
                        return
                if len(pending) > MAX_EVENT:
                    raise AddisAIError("Scribe event exceeds the limit.")
            if pending.strip():
                event = _parse(pending.decode("utf-8"))
                if event["type"] == "transcript.completed":
                    self.completion = event["data"]
                yield event
            if self.completion is None:
                raise AddisAIError("Scribe ended before billing confirmation. Recover the same request_id.")
        finally:
            self.close()


def connect_scribe(session: Dict[str, Any], *, websocket_factory=None) -> "ScribeConnection":
    """Connect using only a scoped ticket. Install ``addisai[realtime]`` for WebSocket support."""
    url = session["websocket_url"]
    parsed = urlsplit(url)
    if (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path != PATH + "/stream" or
            (parsed.scheme != "wss" and not (parsed.scheme == "ws" and parsed.hostname in ("localhost", "127.0.0.1")))):
        raise AddisAIError("Scribe WebSocket URL must use wss without credentials or query parameters.")
    if websocket_factory is None:
        try:
            from websocket import create_connection
        except ImportError:
            raise AddisAIError('Install WebSocket support with: pip install "addisai[realtime]"') from None
        websocket_factory = create_connection
    socket = websocket_factory(url, timeout=10)
    try:
        socket.send(json.dumps({"type": "session.authenticate", "token": session["token"]}))
        connection = ScribeConnection(socket, session["request_id"])
        first = connection.receive()
        if first["type"] not in ("session.created", "transcript.completed"):
            raise AddisAIError("Scribe session was rejected or expired.")
        connection.session = first
        connection._first = first
        socket.settimeout(600)
        return connection
    except Exception:
        socket.close()
        raise


class ScribeConnection:
    def __init__(self, socket, request_id: str):
        self._socket = socket
        self.request_id = request_id
        self.completion: Optional[Dict[str, Any]] = None
        self.session: Optional[Dict[str, Any]] = None
        self._first = None
        self._closed = False
        self._finishing = False
        self._audio_bytes = 0

    def send_audio(self, audio: bytes) -> None:
        """Send raw 16 kHz mono PCM16 little-endian; 100 ms is 3,200 bytes."""
        if self._closed or self._finishing or self.completion is not None:
            raise AddisAIError("Scribe session is not accepting audio.")
        if not audio or len(audio) % 2 or len(audio) > 64000 or self._audio_bytes + len(audio) > 180 * 32000:
            raise AddisAIError("Scribe needs PCM16 frames up to two seconds and 180 seconds total.")
        self._socket.send_binary(bytes(audio))
        self._audio_bytes += len(audio)

    def finish(self) -> None:
        if not self._closed and not self._finishing and self.completion is None:
            self._socket.send(json.dumps({"type": "audio.finish"}))
            self._finishing = True

    def receive(self) -> Dict[str, Any]:
        message = self._socket.recv()
        if not message:
            self.close()
            raise AddisAIError("Scribe closed before billing confirmation. Recover the same request_id.")
        if len(message) > MAX_EVENT:
            self.close()
            raise AddisAIError("Scribe event exceeds the limit.")
        event = _parse(message)
        if event["type"] == "transcript.completed":
            self.completion = event["data"]
        return event

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        if self._first is not None:
            first, self._first = self._first, None
            yield first
        while not self._closed and self.completion is None:
            yield self.receive()
        if self.completion is None:
            raise AddisAIError("Scribe ended before billing confirmation. Recover the same request_id.")

    def close(self) -> None:
        """Closing after audio is sent still permits settlement on the server."""
        if not self._closed:
            self._closed = True
            self._socket.close()

    def __enter__(self) -> "ScribeConnection":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
