"""Speech-to-text resource."""
from __future__ import annotations

import json as _json
from typing import Any, BinaryIO, Dict, Optional, Tuple, Union

from .._transport import Options, Transport, unwrap_data

AudioInput = Union[bytes, BinaryIO, Tuple[str, Any, str]]


class Speech:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def transcribe(
        self,
        *,
        audio: AudioInput,
        language: str,
        request_options: Optional[Options] = None,
    ) -> Dict[str, Any]:
        """Transcribe speech to text. `language` is one of am|om|en|ha|sw."""
        if isinstance(audio, tuple):
            file_part = audio
        elif isinstance(audio, (bytes, bytearray)):
            file_part = ("audio.wav", bytes(audio), "audio/wav")
        else:
            file_part = ("audio.wav", audio, "audio/wav")

        files = {"audio": file_part}
        data = {"request_data": _json.dumps({"language_code": language})}

        body = unwrap_data(
            self._transport.request(
                "POST", "/api/v2/stt", files=files, data=data, options=request_options
            )
        )
        return {
            "text": body.get("transcription", ""),
            "confidence": body.get("confidence"),
            "usage": body.get("usage_metadata"),
        }
