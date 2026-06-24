"""Voice / text-to-speech resource."""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from .._clip import VoiceClip, map_clip
from .._exceptions import NotSupportedError
from .._idempotency import ulid
from .._streaming import AudioStream
from .._transport import Options, Transport, unwrap_data

_VOICE_TIMEOUT_FLOOR = 95.0  # seconds


class Voice:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self.clips = Clips(transport)

    def generate(
        self,
        *,
        voice_id: str,
        text: str,
        language: str,
        output_format: str = "mp3_44100",
        voice_settings: Optional[Dict[str, float]] = None,
        client_request_id: Optional[str] = None,
        request_options: Optional[Options] = None,
    ) -> VoiceClip:
        """Synthesize speech and return the generated clip."""
        crid = client_request_id or ulid()
        body = {
            "text": text,
            "language": language,
            "voice_id": voice_id,
            "output_format": output_format,
            "voice_settings": voice_settings,
            "stream": False,
            "client_request_id": crid,
        }
        data = unwrap_data(
            self._transport.request(
                "POST",
                "/api/v1/voice/generations",
                json=body,
                timeout_floor=_VOICE_TIMEOUT_FLOOR,
                options=request_options,
            )
        )
        return map_clip(data, self._transport.http_client, crid)

    def stream(self, **_: Any) -> AudioStream:
        """The surface is stable for when the API enables streaming synthesis;
        until then it raises NotSupportedError. Use ``generate`` today."""
        raise NotSupportedError(
            "Streaming voice synthesis is not yet available. Use voice.generate()."
        )

    def estimate(
        self,
        *,
        voice_id: str,
        text: str,
        language: str,
        output_format: str = "mp3_44100",
        request_options: Optional[Options] = None,
    ) -> Dict[str, Any]:
        body = {"text": text, "language": language, "voice_id": voice_id, "output_format": output_format}
        return unwrap_data(
            self._transport.request("POST", "/api/v1/voice/estimate", json=body, options=request_options)
        )

    def usage(self, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        return unwrap_data(
            self._transport.request("GET", "/api/v1/voice/usage", options=request_options)
        )


class Clips:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def list(
        self,
        *,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        language: Optional[str] = None,
        voice_id: Optional[str] = None,
        request_options: Optional[Options] = None,
    ) -> "ClipPage":
        def fetch(cur: Optional[str]) -> Dict[str, Any]:
            query = {"limit": limit, "cursor": cur, "language": language, "voice_id": voice_id}
            return self._transport.request(
                "GET", "/api/v1/voice/clips", query=query, options=request_options
            )

        return ClipPage(self._transport, fetch, fetch(cursor))

    def get(self, clip_id: str, *, request_options: Optional[Options] = None) -> VoiceClip:
        data = unwrap_data(
            self._transport.request(
                "GET", f"/api/v1/voice/clips/{clip_id}", options=request_options
            )
        )
        return map_clip(data, self._transport.http_client)

    def download(self, clip_id: str, *, request_options: Optional[Options] = None) -> bytes:
        return self.get(clip_id, request_options=request_options).content()

    def delete(self, clip_id: str, *, request_options: Optional[Options] = None) -> None:
        self._transport.request(
            "DELETE", f"/api/v1/voice/clips/{clip_id}", raw=True, options=request_options
        )


class ClipPage:
    """Iterable that auto-paginates across all clip pages."""

    def __init__(self, transport: Transport, fetch, first: Dict[str, Any]) -> None:
        self._transport = transport
        self._fetch = fetch
        self._first = first

    @property
    def data(self) -> List[VoiceClip]:
        return [map_clip(c, self._transport.http_client) for c in (self._first.get("data") or [])]

    @property
    def next_cursor(self) -> Optional[str]:
        return (self._first.get("meta") or {}).get("next_cursor")

    def __iter__(self) -> Iterator[VoiceClip]:
        page = self._first
        while True:
            for raw in page.get("data") or []:
                yield map_clip(raw, self._transport.http_client)
            cursor = (page.get("meta") or {}).get("next_cursor")
            if not cursor:
                return
            page = self._fetch(cursor)
