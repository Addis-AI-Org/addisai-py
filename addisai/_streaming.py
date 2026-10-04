"""Streaming response objects: ChatStream (SSE) and AudioStream (audio bytes)."""
from __future__ import annotations

import base64
import json as _json
import time
import uuid
import struct
from typing import Any, Dict, Iterator, List, Optional

import httpx

from ._exceptions import AddisAIError, make_api_error

ADDIS_CHAT_MODEL = "addis-1-alef"


def _raise_for_stream_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    response.read()
    try:
        body = response.json()
    except ValueError:
        body = None
    headers = {k.lower(): v for k, v in response.headers.items()}
    raise make_api_error(response.status_code, body, response.text, headers)


def _iter_sse_data(response: httpx.Response) -> Iterator[str]:
    """Yield the `data` payload string of each SSE event."""
    data_lines: List[str] = []
    for line in response.iter_lines():
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
    if data_lines:
        yield "\n".join(data_lines)


def _finish(reason: Optional[str]) -> Optional[str]:
    if not reason:
        return None
    mapping = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter", "RECITATION": "content_filter", "TOOL_CALLS": "tool_calls"}
    return mapping.get(reason.upper(), reason.lower())


class ChatStream:
    """An OpenAI-style streaming chat response. Iterate to receive chunk dicts."""

    def __init__(self, transport, body: Dict[str, Any], options: Optional[Dict[str, Any]] = None) -> None:
        self._cm = transport.stream("POST", "/api/v1/chat_generate", json=body, options=options)
        self._id = f"chatcmpl-{uuid.uuid4().hex}"
        self._created = int(time.time())
        self._consumed = False
        self.transcription: Optional[Dict[str, Any]] = None
        self._usage: Optional[Dict[str, int]] = None

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        if self._consumed:
            raise AddisAIError("This stream has already been consumed.")
        self._consumed = True
        with self._cm as response:
            _raise_for_stream_status(response)
            for data in _iter_sse_data(response):
                data = data.strip()
                if not data:
                    continue
                if data == "[DONE]":
                    return
                try:
                    payload = _json.loads(data)
                except ValueError:
                    continue
                if payload.get("type") == "metadata":
                    self.transcription = {
                        "raw": payload.get("transcription_raw"),
                        "clean": payload.get("transcription_clean"),
                    }
                    continue
                usage = payload.get("usage_metadata")
                if usage:
                    self._usage = {
                        "prompt_tokens": usage.get("prompt_token_count", 0),
                        "completion_tokens": usage.get("candidates_token_count", 0),
                        "total_tokens": usage.get("total_token_count", 0),
                    }
                content = payload.get("text") or payload.get("response_text") or ""
                finish = _finish(payload.get("finish_reason"))
                if not content and not finish:
                    continue
                yield {
                    "id": self._id,
                    "object": "chat.completion.chunk",
                    "created": self._created,
                    "model": ADDIS_CHAT_MODEL,
                    "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": finish}],
                }

    def final_text(self) -> str:
        """Consume the stream and return the concatenated assistant text."""
        return "".join(c["choices"][0]["delta"].get("content", "") for c in self)

    def final_completion(self) -> Dict[str, Any]:
        """Consume the stream and return an assembled non-streaming completion."""
        content = ""
        finish = "stop"
        for chunk in self:
            content += chunk["choices"][0]["delta"].get("content", "")
            if chunk["choices"][0].get("finish_reason"):
                finish = chunk["choices"][0]["finish_reason"]
        completion = {
            "id": self._id,
            "object": "chat.completion",
            "created": self._created,
            "model": ADDIS_CHAT_MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}],
            "usage": self._usage,
        }
        if self.transcription:
            completion["transcription"] = self.transcription
        return completion


class AudioStream:
    """A stream of audio byte chunks. Iterate to receive ``bytes``. Normalizes
    the two legacy encodings (ndjson base64, or raw audio bytes)."""

    def __init__(self, transport, body: Dict[str, Any], options: Optional[Dict[str, Any]] = None,
                 *, path: str = "/api/v1/audio", voice: bool = False) -> None:
        self._cm = transport.stream("POST", path, json=body, options=options)
        self._consumed = False
        self._voice = voice
        self._transport = transport
        self._options = options or {}
        self._response: Optional[httpx.Response] = None
        self.metadata: Optional[Dict[str, Any]] = None
        self.client_request_id: Optional[str] = body.get("client_request_id")

    def __iter__(self) -> Iterator[bytes]:
        if self._consumed:
            raise AddisAIError("This stream has already been consumed.")
        self._consumed = True
        with self._cm as response:
            self._response = response
            _raise_for_stream_status(response)
            if self._voice:
                if response.headers.get("x-addis-audio-protocol") == "mp3-frames-v1":
                    for part in _iter_voice_frames(response):
                        if isinstance(part, bytes):
                            yield part
                        else:
                            self.metadata = part
                elif "application/json" in response.headers.get("content-type", ""):
                    response.read()
                    self.metadata = response.json().get("data")
                    if not self.metadata or not self.metadata.get("audio_url"):
                        raise AddisAIError("Invalid voice replay metadata.")
                    # Download the saved, already-paid clip on an idempotent replay.
                    with self._transport.http_client.stream("GET", self.metadata["audio_url"],
                                                            timeout=self._options.get("timeout", 190)) as audio:
                        _raise_for_stream_status(audio)
                        yield from audio.iter_bytes()
                else:
                    raise AddisAIError("Unsupported voice stream protocol.")
                return
            ctype = response.headers.get("content-type", "").lower()
            if "ndjson" in ctype or "json" in ctype:
                for line in response.iter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = _json.loads(line)
                    except ValueError:
                        continue
                    if obj.get("status") == "error" or obj.get("error"):
                        raise AddisAIError((obj.get("error") or {}).get("message", "Audio stream failed."))
                    b64 = obj.get("audio_chunk") or obj.get("audio")
                    if b64:
                        yield base64.b64decode(b64)
            else:
                for chunk in response.iter_bytes():
                    if chunk:
                        yield chunk

    def read(self) -> bytes:
        """Collect every chunk into a single bytes object."""
        return b"".join(self)

    def close(self) -> None:
        """Stop reading and close the underlying HTTP response."""
        if self._response is not None:
            self._response.close()

    def to_file(self, path: str) -> None:
        """Stream the audio to a file on disk."""
        with open(path, "wb") as fh:
            for chunk in self:
                fh.write(chunk)


def _iter_voice_frames(response: httpx.Response) -> Iterator[Any]:
    pending = bytearray()
    terminal = False
    total = 0
    for chunk in response.iter_bytes():
        pending.extend(chunk)
        if terminal:
            if len(pending) > 128 * 1024:
                raise AddisAIError("Voice metadata exceeds the limit.")
            continue
        while len(pending) >= 4:
            size = struct.unpack_from(">I", pending)[0]
            if size == 0:
                del pending[:4]
                terminal = True
                break
            if size > 2 * 1024 * 1024:
                raise AddisAIError("Voice frame exceeds the limit.")
            if len(pending) < size + 4:
                break
            total += size
            if total > 16 * 1024 * 1024:
                raise AddisAIError("Voice audio exceeds the limit.")
            yield bytes(pending[4:4 + size])
            del pending[:4 + size]
        if terminal and len(pending) > 128 * 1024:
            raise AddisAIError("Voice metadata exceeds the limit.")
    if not terminal:
        raise AddisAIError("Voice stream ended before billing confirmation. Retry with the same client_request_id.")
    try:
        data = _json.loads(pending)
    except ValueError:
        raise AddisAIError("Invalid voice completion metadata.") from None
    if not isinstance(data, dict) or not isinstance(data.get("data"), dict) or data.get("error"):
        raise AddisAIError("Voice generation did not complete.")
    yield data["data"]
