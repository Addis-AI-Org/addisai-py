"""Deprecated legacy /audio endpoint, kept only as a migration bridge."""
from __future__ import annotations

import base64
import warnings
from typing import Optional

from .._exceptions import AddisAIError
from .._streaming import AudioStream
from .._transport import Options, Transport

_warned = False


def _warn_once() -> None:
    global _warned
    if _warned:
        return
    _warned = True
    warnings.warn(
        "addis.legacy.audio is deprecated. Migrate to addis.voice.generate(), which uses "
        "the current, more capable voice model. The legacy /audio endpoint may be removed "
        "in a future release.",
        DeprecationWarning,
        stacklevel=3,
    )


class LegacyAudioResult:
    def __init__(self, audio_b64: str) -> None:
        #: Base64-encoded audio (WAV or MP3, provider-dependent).
        self.audio = audio_b64

    def content(self) -> bytes:
        return base64.b64decode(self.audio)

    def to_file(self, path: str) -> None:
        with open(path, "wb") as fh:
            fh.write(self.content())


class LegacyAudio:
    """Deprecated. Use ``addis.voice`` instead."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def generate(
        self, *, text: str, language: str, request_options: Optional[Options] = None
    ) -> LegacyAudioResult:
        """Deprecated. Synthesize speech via the legacy endpoint (non-streaming, 1500-char cap)."""
        _warn_once()
        body = self._transport.request(
            "POST",
            "/api/v1/audio",
            json={"text": text, "language": language, "stream": False},
            options=request_options,
        )
        audio = (body or {}).get("audio") or (body or {}).get("audio_chunk")
        if not audio:
            raise AddisAIError("Legacy audio response did not contain audio data.")
        return LegacyAudioResult(audio)

    def stream(
        self, *, text: str, language: str, request_options: Optional[Options] = None
    ) -> AudioStream:
        """Deprecated. Stream synthesis via the legacy endpoint. Returns an
        :class:`AudioStream` of audio byte chunks (handles both legacy encodings)."""
        _warn_once()
        return AudioStream(
            self._transport,
            {"text": text, "language": language, "stream": True},
            options=request_options,
        )


class Legacy:
    """Deprecated namespace retained for backward compatibility."""

    def __init__(self, transport: Transport) -> None:
        self.audio = LegacyAudio(transport)
