"""Voice catalog resource."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .._transport import Options, Transport, unwrap_data


class Voices:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def list(
        self,
        *,
        language: Optional[str] = None,
        gender: Optional[str] = None,
        search: Optional[str] = None,
        include_unavailable: Optional[bool] = None,
        request_options: Optional[Options] = None,
    ) -> List[Dict[str, Any]]:
        query = {
            "language": language,
            "gender": gender,
            "search": search,
            "include_unavailable": include_unavailable,
        }
        return unwrap_data(
            self._transport.request("GET", "/api/v1/voice/voices", query=query, options=request_options)
        )

    def preview(self, voice_id: str, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        return unwrap_data(
            self._transport.request(
                "GET", f"/api/v1/voice/voices/{voice_id}/preview", options=request_options
            )
        )
