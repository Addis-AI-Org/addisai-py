"""Addis Scribe transcription (Amharic and Afaan Oromo). Account credentials stay on the application server."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import time
from typing import Any, BinaryIO, Callable, Dict, Iterator, Optional, Union
from urllib.parse import urlsplit

from .._exceptions import AddisAIError, APIConnectionError, APIError, make_api_error
from .._idempotency import ulid
from .._languages import ScribeLanguage
from .._transport import Options, Transport, _parse_json, _to_error, unwrap_data
from .speech import AudioInput

PATH = "/api/v1/scribe"
MAX_EVENT = 512 * 1024
BACKENDS = ("standard", "turbo")
TIMESTAMPS = ("none", "word")
LIVE_SECONDS = 900       # default live session limit; the server's session.created carries the real one
POLL_SECONDS = 5
POLL_LIMIT = 3600        # give up polling a long upload after an hour
MAX_UPLOAD_BYTES = 95 * 1024**2   # the largest one-request upload (/transcribe and one-request jobs)
PART_BYTES = 4 * 1024**2          # job part size; the create response carries the server's value
PART_RETRIES = 3                  # a part is sent again this many times after a connection error
JOB_POLL_SECONDS = 5
JOB_POLL_LIMIT = 4 * 3600         # give up waiting for a job after four hours

LongAudioInput = Union[AudioInput, str, "os.PathLike[str]"]


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


def _language(value):
    """Validate ``language``; it reaches the wire only when the caller sets it (omitted means Amharic).

    Other language codes go to the API, which answers ``422 UNSUPPORTED_LANGUAGE``; Afaan Oromo
    (``"om"``) with ``backend="standard"`` is refused there too (``422``).
    """
    if value is None:
        return {}
    if not isinstance(value, str) or not value:
        raise AddisAIError('Scribe language must be "am" (Amharic) or "om" (Afaan Oromo).')
    return {"language": value}


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


def _job_params(backend, chunk, request_id, timestamps, speakers, language=None):
    """Validate job parameters. Unlike ``transcribe``, a job always sends ``timestamps`` (default ``"word"``)."""
    _timestamps(timestamps)
    return {**_params(backend, chunk, request_id), "timestamps": timestamps, **_speakers(speakers, backend),
            **_language(language)}


def _index(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AddisAIError("Scribe part index must be a non-negative integer.")
    return value


def _progress(data):
    if not isinstance(data, dict):
        raise AddisAIError("Invalid Scribe job response.")
    return data


class _Source:
    """Long audio to send: its size, a whole-file multipart part, and byte ranges read on demand."""

    def __init__(self, audio: Any) -> None:
        self.name, self.content_type, self._owned = "audio.wav", "audio/wav", False
        if isinstance(audio, tuple):
            if len(audio) != 3:
                raise AddisAIError("Scribe audio tuples are (filename, data, content_type).")
            self.name, audio, self.content_type = audio
        if isinstance(audio, (str, os.PathLike)):
            path = os.fspath(audio)
            self.name = os.path.basename(path) or self.name
            self.content_type = mimetypes.guess_type(self.name)[0] or "application/octet-stream"
            self._file: Optional[BinaryIO] = open(path, "rb")
            self._owned = True
            self._bytes: Optional[bytes] = None
        elif isinstance(audio, (bytes, bytearray)):
            self._file, self._bytes = None, bytes(audio)
        elif hasattr(audio, "read"):
            if hasattr(audio, "seekable") and not audio.seekable():
                self._file, self._bytes = None, audio.read()
            else:
                self._file, self._bytes = audio, None
        else:
            raise AddisAIError("Scribe audio must be bytes, a binary file object, a path or a (filename, data, content_type) tuple.")
        if self._file is not None:
            self._file.seek(0, os.SEEK_END)
            self.size = self._file.tell()
            self._file.seek(0)
        else:
            self.size = len(self._bytes or b"")
        if self.size <= 0:
            raise AddisAIError("Scribe audio is empty.")

    def whole(self) -> Any:
        """The whole file as a multipart part: (filename, bytes or file object, content_type)."""
        return (self.name, self._bytes if self._file is None else self._file, self.content_type)

    def read(self, start: int, length: int) -> bytes:
        """Exactly ``length`` bytes from ``start`` (fewer only at the end of the file)."""
        if self._file is None:
            return (self._bytes or b"")[start:start + length]
        self._file.seek(start)
        pieces, remaining = [], length
        while remaining > 0:
            piece = self._file.read(remaining)
            if not piece:
                break
            pieces.append(piece)
            remaining -= len(piece)
        return b"".join(pieces)

    def close(self) -> None:
        if self._owned and self._file is not None:
            self._file.close()


def _files(audio):
    if isinstance(audio, tuple):
        part = audio
    elif isinstance(audio, (bytes, bytearray)):
        if not audio or len(audio) > 95 * 1024**2:
            raise AddisAIError("Scribe audio must contain 1 byte to 95 MiB.")
        part = ("audio.wav", bytes(audio), "audio/wav")
    else:
        part = ("audio.wav", audio, "audio/wav")
    return {"audio": part}


class Scribe:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self.jobs = ScribeJobs(transport)

    def capabilities(self, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        return unwrap_data(self._transport.request("GET", PATH, options=request_options))

    def usage(self, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        return unwrap_data(self._transport.request("GET", PATH + "/usage", options=request_options))

    def recover(self, request_id: str, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        _params("standard", "1120ms", request_id)
        return _completion(unwrap_data(self._transport.request("GET", PATH + "/requests/" + request_id,
                           options={**(request_options or {}), "max_retries": 0})))

    def transcribe(self, *, audio: AudioInput, backend: str = "turbo", chunk: str = "1120ms",
                   request_id: Optional[str] = None, timestamps: str = "none", speakers: bool = False,
                   language: Optional[ScribeLanguage] = None,
                   request_options: Optional[Options] = None) -> Dict[str, Any]:
        """Transcribe an Amharic or Afaan Oromo file. No automatic retries; recover its request_id after interruptions.

        ``backend`` is ``"turbo"`` (default) or ``"standard"``. ``timestamps="word"`` adds ``words``
        and caption ``segments`` to the result (default ``"none"``, which sends no ``timestamps`` parameter).
        ``speakers=True`` (turbo only; default ``False``, which sends no ``speakers`` parameter) turns on
        word timestamps and adds a ``speaker`` number (or ``None``) to every word and segment, plus a
        ``speakers`` count to the result.

        ``language`` is ``"am"`` (Amharic) or ``"om"`` (Afaan Oromo, turbo only); the default ``None``
        sends no ``language`` parameter, which means Amharic.
        """
        params = {**_params(backend, chunk, request_id), **_timestamps(timestamps), **_speakers(speakers, backend),
                  **_language(language)}
        data = unwrap_data(self._transport.request("POST", PATH + "/transcribe",
                           query={**params, "stream": "false"}, files=_files(audio), timeout_floor=600,
                           options={**(request_options or {}), "max_retries": 0}))
        return _completion(self._settled(data, request_options))

    def _settled(self, data, request_options):
        """A long upload answers 202 with ``status: "processing"``; poll its request until it is done."""
        if not (isinstance(data, dict) and data.get("status") == "processing"):
            return data
        deadline = time.monotonic() + POLL_LIMIT
        while True:
            time.sleep(POLL_SECONDS)
            try:
                return unwrap_data(self._transport.request("GET", PATH + "/requests/" + data["request_id"],
                                   options={**(request_options or {}), "max_retries": 0}))
            except APIError as exc:
                if exc.code != "IN_PROGRESS" or time.monotonic() > deadline:
                    raise

    def transcribe_long(self, *, audio: LongAudioInput, backend: str = "turbo", chunk: str = "1120ms",
                        request_id: Optional[str] = None, timestamps: str = "word", speakers: bool = False,
                        on_progress: Optional[Callable[[Dict[str, Any]], Any]] = None,
                        language: Optional[ScribeLanguage] = None,
                        request_options: Optional[Options] = None) -> Dict[str, Any]:
        """Transcribe a long Amharic or Afaan Oromo file (up to three hours) as a job and wait for its result.

        ``audio`` is ``bytes``, a seekable binary file object (read from its start), a path (``str`` or
        ``os.PathLike``, opened in binary mode) or a ``(filename, data, content_type)`` tuple. A file of
        at most 95 MiB goes up in one request (``jobs.upload``); a larger one is declared
        (``jobs.create``) and sent as 4 MiB parts in index order, skipping parts the server already
        holds and sending a part again after a connection error, then ``jobs.complete``. The result is
        then polled every 5 seconds (honouring ``Retry-After``) for up to four hours; ``on_progress``
        receives each progress dict (``audio_seconds``, ``processed_seconds``, ``chunks``, ...).

        ``backend`` must be ``"turbo"`` for long files (``"standard"`` is refused by the API).
        ``timestamps`` defaults to ``"word"`` for jobs (``words`` and ``segments`` in the result); pass
        ``"none"`` for text only. ``speakers=True`` adds speaker numbers over the whole file.
        ``request_id`` (default: a new ULID) names every call of the job; keep it to ``recover`` the
        result after an interruption. Paid steps are never retried automatically.

        ``language`` is ``"am"`` (Amharic) or ``"om"`` (Afaan Oromo, turbo only); the default ``None``
        sends no ``language`` parameter, which means Amharic.

        Interrupting the upload (``KeyboardInterrupt``, e.g. Ctrl-C) cancels the job (``jobs.cancel``)
        before the interrupt propagates, so an abandoned upload does not hold one of the account's
        long-file slots. Once the job is queued, an interrupt only stops the waiting: the job runs on
        and is read later with ``recover(request_id)`` (or call ``jobs.cancel`` yourself).
        """
        params = _job_params(backend, chunk, request_id, timestamps, speakers, language)
        rid = params["request_id"]
        source = _Source(audio)
        try:
            if source.size <= MAX_UPLOAD_BYTES:
                self.jobs.upload(audio=source.whole(), backend=backend, chunk=chunk, request_id=rid,
                                 timestamps=timestamps, speakers=speakers, language=language,
                                 request_options=request_options)
            else:
                job = self.jobs.create(request_id=rid, bytes=source.size, backend=backend, chunk=chunk,
                                       timestamps=timestamps, speakers=speakers, language=language,
                                       request_options=request_options)
                part_bytes = int(job.get("part_bytes") or PART_BYTES)
                parts = int(job.get("parts") or -(-source.size // part_bytes))
                received = set(job.get("received") or ())
                for index in range(parts):
                    if index in received:
                        continue
                    self.jobs._put_part_retrying(rid, index, source.read(index * part_bytes, part_bytes), request_options)
                self.jobs.complete(rid, request_options=request_options)
        except KeyboardInterrupt:
            self.jobs._cancel_quietly(rid, request_options)
            raise
        finally:
            source.close()
        return self.jobs.wait(rid, on_progress=on_progress, request_options=request_options)

    def stream(self, *, audio: AudioInput, backend: str = "turbo", chunk: str = "1120ms",
               request_id: Optional[str] = None, timestamps: str = "none", speakers: bool = False,
               language: Optional[ScribeLanguage] = None,
               request_options: Optional[Options] = None) -> "ScribeTranscriptStream":
        """Upload a file, then iterate partials and settled completion. Use as a context manager.

        ``backend`` defaults to ``"turbo"``. Word timestamps and speaker labels are not available here;
        use transcribe().

        ``language`` is ``"am"`` (Amharic) or ``"om"`` (Afaan Oromo, turbo only); the default ``None``
        sends no ``language`` parameter, which means Amharic.
        """
        if speakers is True:
            raise AddisAIError('Scribe speaker labels are available only for completed uploads; '
                               'use transcribe(backend="turbo", speakers=True) instead of stream().')
        _speakers(speakers, "turbo")
        if _timestamps(timestamps).get("timestamps") == "word":
            raise AddisAIError('Scribe timestamps are available only for completed uploads; '
                               'use transcribe(timestamps="word") instead of stream().')
        params = _params(backend, chunk, request_id)
        context = self._transport.stream("POST", PATH + "/transcribe",
                                        query={**params, **_language(language), "stream": "true"},
                                        files=_files(audio), options={"timeout": 600, **(request_options or {})})
        return ScribeTranscriptStream(context, params["request_id"])

    def create_session(self, *, backend: str = "turbo", chunk: str = "320ms", request_id: Optional[str] = None,
                       language: Optional[ScribeLanguage] = None,
                       request_options: Optional[Options] = None) -> Dict[str, Any]:
        """Create a one-use ticket on your server, with no automatic issuance retries.

        ``language`` is ``"am"`` (Amharic) or ``"om"`` (Afaan Oromo, turbo only), sent in the JSON body;
        the default ``None`` leaves it out, which means Amharic.
        """
        body = {**_params(backend, chunk, request_id), **_language(language)}
        return unwrap_data(self._transport.request("POST", PATH + "/sessions", json=body,
                          options={**(request_options or {}), "max_retries": 0}))

    def connect(self, *, backend: str = "turbo", chunk: str = "320ms", request_id: Optional[str] = None,
                language: Optional[ScribeLanguage] = None,
                request_options: Optional[Options] = None, websocket_factory=None) -> "ScribeConnection":
        """Create a ticket (see ``create_session``, including ``language``) and open its socket."""
        session = self.create_session(backend=backend, chunk=chunk, request_id=request_id, language=language,
                                      request_options=request_options)
        return connect_scribe(session, websocket_factory=websocket_factory)


class ScribeJobs:
    """Long-audio jobs (``scribe.jobs``): the steps behind ``transcribe_long``, for callers that need them one at a time.

    Every method returns the ``data`` dict of the API response as it is. Paid steps (``upload``,
    ``create``, ``put_part``, ``complete``) are never retried automatically.
    """

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def upload(self, *, audio: AudioInput, backend: str = "turbo", chunk: str = "1120ms",
               request_id: Optional[str] = None, timestamps: str = "word", speakers: bool = False,
               language: Optional[ScribeLanguage] = None,
               request_options: Optional[Options] = None) -> Dict[str, Any]:
        """Create a job from a file of at most 95 MiB in one multipart request; the job starts at once.

        Returns the job's first state (``status: "queued"``, ``poll_url``, ``job_url``), or the current
        state when the same file and settings were already sent under ``request_id``. ``audio`` is
        ``bytes``, a binary file object or a ``(filename, data, content_type)`` tuple. Larger files go
        through ``create`` and ``put_part``.

        ``language`` is ``"am"`` (Amharic) or ``"om"`` (Afaan Oromo, turbo only); the default ``None``
        sends no ``language`` parameter, which means Amharic.
        """
        params = _job_params(backend, chunk, request_id, timestamps, speakers, language)
        data = audio[1] if isinstance(audio, tuple) else audio
        if isinstance(data, (bytes, bytearray)) and len(data) > MAX_UPLOAD_BYTES:
            raise AddisAIError("Scribe jobs.upload takes at most 95 MiB in one request; "
                               "declare larger files with jobs.create and send jobs.put_part ranges (or use transcribe_long).")
        part = audio if isinstance(audio, tuple) else _files(audio)["audio"]
        return _progress(unwrap_data(self._transport.request(
            "POST", PATH + "/jobs", query=params, files={"audio": part}, timeout_floor=600,
            options={**(request_options or {}), "max_retries": 0})))

    def create(self, *, request_id: str, bytes: int, backend: str = "turbo", chunk: str = "1120ms",
               timestamps: str = "word", speakers: bool = False, language: Optional[ScribeLanguage] = None,
               request_options: Optional[Options] = None) -> Dict[str, Any]:
        """Declare a job of ``bytes`` bytes (up to 512 MB) to be sent as parts.

        Returns ``part_bytes``, ``parts``, ``received`` (indexes already held; resume from there when
        the same declaration is sent again) and ``expires_at``: the Unix time at which the unfinished
        upload expires, 30 minutes after its last new part (or the declaration). Each new part moves it
        forward, never past 24 hours after the declaration; status reads, a new declaration and a resent
        part do not. Once it passes, the job is gone (``404 NOT_FOUND``), it no longer counts toward the
        account's two long files, and the request ID is free: declare it again to start over.

        ``language`` is ``"am"`` (Amharic) or ``"om"`` (Afaan Oromo), sent as the ``language`` query
        parameter; the default ``None`` sends none, which means Amharic.
        """
        if isinstance(bytes, bool) or not isinstance(bytes, int) or bytes <= 0:
            raise AddisAIError("Scribe job bytes must be a positive integer: the size of the file.")
        params = _job_params(backend, chunk, request_id, timestamps, speakers, language)
        body = {"request_id": params["request_id"], "bytes": bytes, "backend": backend, "chunk": chunk,
                "timestamps": timestamps, "speakers": speakers}
        return _progress(unwrap_data(self._transport.request(
            "POST", PATH + "/jobs", json=body, query=_language(language) or None, options={**(request_options or {}), "max_retries": 0})))

    def put_part(self, request_id: str, index: int, data: bytes, *,
                 request_options: Optional[Options] = None) -> Dict[str, Any]:
        """Send part ``index``: the file's bytes ``[index * part_bytes, (index + 1) * part_bytes)``.

        Every part but the last is exactly ``part_bytes`` long. Returns ``index`` and the ``received``
        list so far. While the upload is open, sending a stored part again with the same bytes is a
        no-op. After ``complete``, or for a job made with ``upload``, the job takes no more parts:
        ``409 UPLOAD_CLOSED``.
        """
        _params("turbo", "1120ms", request_id)
        _index(index)
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise AddisAIError("Scribe part data must be non-empty bytes.")
        return _progress(unwrap_data(self._transport.request(
            "PUT", PATH + "/jobs/" + request_id + "/parts/" + str(index), content=bytes(data), timeout_floor=120,
            options={**(request_options or {}), "max_retries": 0})))

    def _put_part_retrying(self, request_id, index, data, request_options):
        """``put_part`` sent again after a connection error (never after an API error)."""
        for attempt in range(PART_RETRIES + 1):
            try:
                return self.put_part(request_id, index, data, request_options=request_options)
            except APIConnectionError:
                if attempt >= PART_RETRIES:
                    raise
                time.sleep(0.5 * 2 ** attempt)

    def complete(self, request_id: str, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        """Start the job once every part is there (``409 UPLOAD_INCOMPLETE`` with ``missing`` otherwise).

        Returns the queued state; calling it again returns the state while it runs and the result once done.
        """
        _params("turbo", "1120ms", request_id)
        return _progress(unwrap_data(self._transport.request(
            "POST", PATH + "/jobs/" + request_id + "/complete", options={**(request_options or {}), "max_retries": 0})))

    def cancel(self, request_id: str, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        """Cancel a job; nothing is charged, also for a job stopped while processing.

        An upload or a queued job is removed and its request ID is free again; a processing job is
        stopped and ends failed with ``REQUEST_CANCELLED`` (its request ID stays used). Returns
        ``{"request_id", "status": "cancelled", "was", "request_id_reusable"}``. A finished job raises
        ``409 JOB_FINISHED``; an unknown one ``404 NOT_FOUND``.
        """
        _params("turbo", "1120ms", request_id)
        return unwrap_data(self._transport.request("DELETE", PATH + "/jobs/" + request_id, options=request_options))

    def _cancel_quietly(self, request_id, request_options):
        """``cancel`` for an interrupted upload: best effort (the job may not exist yet), never raises."""
        try:
            self.cancel(request_id, request_options={**(request_options or {}), "max_retries": 0, "timeout": 15})
        except Exception:
            pass

    def status(self, request_id: str, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        """The job's state and progress: ``status``, ``received``/``parts``/``part_bytes``,
        ``audio_seconds``, ``processed_seconds``, ``chunks``, ``poll_url``, ``error`` when failed, and
        ``expires_at`` (for an unfinished upload, see ``create``)."""
        _params("turbo", "1120ms", request_id)
        return _progress(unwrap_data(self._transport.request("GET", PATH + "/jobs/" + request_id, options=request_options)))

    def wait(self, request_id: str, *, on_progress: Optional[Callable[[Dict[str, Any]], Any]] = None,
             poll_seconds: float = JOB_POLL_SECONDS, timeout: float = JOB_POLL_LIMIT,
             request_options: Optional[Options] = None) -> Dict[str, Any]:
        """Poll the job's result until it is settled and return it (the same shape as ``transcribe``).

        Each ``202`` progress body goes to ``on_progress``; the SDK then sleeps ``Retry-After`` seconds
        (``poll_seconds`` when absent). A failed job raises its own API error (``402``, ``422``, ``409``);
        after ``timeout`` seconds an ``AddisAIError`` asks you to ``recover`` the request later.
        """
        _params("turbo", "1120ms", request_id)
        deadline = time.monotonic() + timeout
        while True:
            response = self._transport.request("GET", PATH + "/requests/" + request_id, raw=True,
                                               options={**(request_options or {}), "max_retries": 0})
            data = unwrap_data(_parse_json(response))
            if response.status_code != 202:
                return _completion(data)
            if on_progress is not None:
                on_progress(_progress(data))
            if time.monotonic() > deadline:
                raise AddisAIError(f"Scribe job {request_id} is still running after {timeout:g} seconds; "
                                   "recover the same request_id later.")
            time.sleep(_retry_after(response.headers.get("retry-after"), poll_seconds))


def _retry_after(value, fallback):
    try:
        return max(0.0, float(value)) if value is not None else fallback
    except ValueError:
        return fallback


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
        socket.settimeout(max(600, float(first.get("max_audio_seconds") or LIVE_SECONDS) + 60))
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
        limit = float((self.session or {}).get("max_audio_seconds") or LIVE_SECONDS)
        if not audio or len(audio) % 2 or len(audio) > 64000 or self._audio_bytes + len(audio) > limit * 32000:
            raise AddisAIError(f"Scribe needs PCM16 frames up to two seconds and {limit:g} seconds total.")
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
