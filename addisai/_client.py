from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from ._env import API_KEY_ENV_VAR, redact_api_key, resolve_base_url
from ._exceptions import AddisAIError
from ._transport import Transport
from .resources import Chat, Legacy, Speech, Translate, Voice, Voices


class AddisAI:
    """Client for the Addis AI API — voice, chat/LLM, speech-to-text, translation."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        default_headers: Optional[Dict[str, str]] = None,
        default_query: Optional[Dict[str, str]] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        key = api_key or os.environ.get(API_KEY_ENV_VAR)
        if not key:
            raise AddisAIError(
                f"Missing API key. Pass api_key= or set the {API_KEY_ENV_VAR} environment variable."
            )
        self._api_key = key
        self._transport = Transport(
            api_key=key,
            base_url=resolve_base_url(base_url),
            timeout=timeout,
            max_retries=max_retries,
            default_headers=default_headers or {},
            default_query=default_query or {},
            http_client=http_client,
        )

        self.chat = Chat(self._transport)
        self.voice = Voice(self._transport)
        self.voices = Voices(self._transport)
        self.speech = Speech(self._transport)
        self.translate = Translate(self._transport)
        #: Deprecated. Use ``voice``.
        self.legacy = Legacy(self._transport)

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "AddisAI":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f'AddisAI(api_key="{redact_api_key(self._api_key)}")'
