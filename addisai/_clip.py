"""Generated audio clip object with download helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from ._exceptions import AddisAIError


@dataclass
class VoiceClip:
    id: str
    text: str
    text_preview: str
    voice_id: str
    voice_name: str
    voice_descriptor: str
    language: str
    output_format: str
    audio_url: str
    mime_type: str
    duration_seconds: Optional[float]
    character_count: int
    billable_characters: int
    download_name: str
    created_at: str
    usage: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None
    client_request_id: Optional[str] = None
    _http: Optional[httpx.Client] = field(default=None, repr=False, compare=False)

    def content(self) -> bytes:
        """Fetch the audio bytes from the signed playback URL."""
        if not self.audio_url:
            raise AddisAIError("This clip has no audio_url to download.")
        client = self._http or httpx.Client()
        resp = client.get(self.audio_url)
        if resp.status_code >= 400:
            raise AddisAIError(f"Failed to download clip {self.id}: HTTP {resp.status_code}.")
        return resp.content

    def to_file(self, path: str) -> None:
        """Write the audio to a file on disk."""
        with open(path, "wb") as fh:
            fh.write(self.content())


# Whitelisted fields exposed publicly; provider-specific knobs are dropped.
def map_clip(raw: Dict[str, Any], http: Optional[httpx.Client], client_request_id: Optional[str] = None) -> VoiceClip:
    usage = raw.get("usage")
    meta = raw.get("meta")
    playback = raw.get("playback") or {}
    return VoiceClip(
        id=raw.get("id"),
        text=raw.get("text") or raw.get("text_preview") or "",
        text_preview=raw.get("text_preview") or "",
        voice_id=raw.get("voice_id"),
        voice_name=raw.get("voice_name"),
        voice_descriptor=raw.get("voice_descriptor"),
        language=raw.get("language"),
        output_format=raw.get("output_format"),
        audio_url=raw.get("audio_url") or playback.get("url") or "",
        mime_type=raw.get("mime_type"),
        duration_seconds=raw.get("duration_seconds"),
        character_count=raw.get("character_count") or 0,
        billable_characters=raw.get("billable_characters") or 0,
        download_name=raw.get("download_name") or "",
        created_at=raw.get("created_at"),
        usage={
            "pricing_unit": usage.get("pricing_unit", "minute"),
            "price_per_minute": usage.get("price_per_minute"),
            "price_per_audio_minute": usage.get("price_per_audio_minute"),
            "price_per_1000_characters": usage.get("price_per_1000_characters"),
            "credits_used": usage.get("credits_used"),
            "credits_remaining": usage.get("credits_remaining"),
            "currency": usage.get("currency", "ETB"),
        }
        if isinstance(usage, dict)
        else None,
        meta={
            "ignored_voice_settings": meta.get("ignored_voice_settings", []),
            "idempotent_replay": bool(meta.get("idempotent_replay")),
        }
        if isinstance(meta, dict)
        else None,
        client_request_id=client_request_id,
        _http=http,
    )
