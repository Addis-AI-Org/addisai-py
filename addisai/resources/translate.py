"""Translation resource."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .._transport import Options, Transport, unwrap_data


class Translate:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def create(
        self,
        *,
        text: str,
        source: str,
        target: str,
        request_options: Optional[Options] = None,
    ) -> Dict[str, Any]:
        """Translate text between am|om|en. `source` must differ from `target`."""
        body = {"text": text, "source_language": source, "target_language": target}
        data = unwrap_data(
            self._transport.request("POST", "/api/v1/translate", json=body, options=request_options)
        )
        return {
            "text": data.get("translation", ""),
            "source_language": data.get("source_language", source),
            "target_language": data.get("target_language", target),
            "quality": data.get("quality"),
            "usage": data.get("usage_metadata"),
        }
