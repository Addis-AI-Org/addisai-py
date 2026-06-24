"""Core HTTP transport: auth headers, timeout, retries with backoff, and
error normalization. Built on httpx."""
from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional

import httpx

from ._exceptions import (
    APIConnectionError,
    APIConnectionTimeoutError,
    make_api_error,
)
from ._version import __version__

# Per-request options forwarded by resource methods. All keys optional:
#   timeout (float, seconds), max_retries (int), idempotency_key (str),
#   headers (dict), query (dict)
Options = Dict[str, Any]


class Transport:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float,
        max_retries: int,
        default_headers: Dict[str, str],
        default_query: Dict[str, str],
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._default_headers = default_headers
        self._default_query = default_query
        self._client = http_client or httpx.Client(timeout=timeout)

    @property
    def http_client(self) -> httpx.Client:
        return self._client

    def close(self) -> None:
        self._client.close()

    def _headers(self, request: Dict[str, Any], options: Options) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"addisai-python/{__version__}",
            "X-Addis-Client": f"addisai-python/{__version__}",
        }
        # Auth: API keys go in x-api-key. A Supabase JWT goes in Authorization.
        # Never send both — the voice function rejects a non-JWT bearer token.
        if _looks_like_jwt(self._api_key):
            headers["Authorization"] = f"Bearer {self._api_key}"
        else:
            headers["x-api-key"] = self._api_key
        headers.update(self._default_headers)
        headers.update(options.get("headers") or {})
        if options.get("idempotency_key"):
            headers["Idempotency-Key"] = options["idempotency_key"]
        if request.get("json") is not None and not request.get("files"):
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _is_retryable(status: int, headers: httpx.Headers) -> bool:
        if status in (408, 425, 429):
            return True
        if status == 409:
            return "retry-after" in headers
        return status >= 500

    @staticmethod
    def _retry_delay(attempt: int, headers: Optional[httpx.Headers]) -> float:
        if headers is not None and "retry-after" in headers:
            try:
                return min(float(headers["retry-after"]), 60.0)
            except ValueError:
                pass
        base = min(0.5 * (2 ** attempt), 8.0)
        return base * (0.5 + random.random() * 0.5)

    def stream(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        query: Optional[Dict[str, Any]] = None,
        options: Optional[Options] = None,
    ):
        """Open a streaming request. Returns an httpx streaming context manager;
        streams are not retried once started."""
        options = options or {}
        merged_query = {**self._default_query, **(query or {}), **(options.get("query") or {})}
        merged_query = {k: v for k, v in merged_query.items() if v is not None}
        url = self._base_url + path
        headers = self._headers({"json": json, "files": None}, options)
        timeout = options.get("timeout", self._timeout)
        return self._client.stream(
            method, url, params=merged_query or None, json=json, headers=headers, timeout=timeout
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Dict[str, Any]] = None,
        json: Any = None,
        files: Any = None,
        data: Any = None,
        raw: bool = False,
        timeout_floor: Optional[float] = None,
        options: Optional[Options] = None,
    ) -> Any:
        options = options or {}
        max_retries = options.get("max_retries", self._max_retries)
        timeout = options.get("timeout", self._timeout)
        if timeout_floor and timeout < timeout_floor and "timeout" not in options:
            timeout = timeout_floor

        merged_query = {**self._default_query, **(query or {}), **(options.get("query") or {})}
        merged_query = {k: v for k, v in merged_query.items() if v is not None}
        url = self._base_url + path
        headers = self._headers({"json": json, "files": files}, options)

        last_error: Optional[BaseException] = None
        for attempt in range(max_retries + 1):
            try:
                response = self._client.request(
                    method,
                    url,
                    params=merged_query or None,
                    json=json if files is None else None,
                    data=data,
                    files=files,
                    headers=headers,
                    timeout=timeout,
                )
            except httpx.TimeoutException as exc:
                last_error = APIConnectionTimeoutError(f"Request timed out after {timeout}s.")
                last_error.__cause__ = exc
            except httpx.TransportError as exc:
                last_error = APIConnectionError("Connection error.", cause=exc)
            else:
                if response.is_success:
                    return response if raw else _parse_json(response)
                if attempt < max_retries and self._is_retryable(response.status_code, response.headers):
                    time.sleep(self._retry_delay(attempt, response.headers))
                    continue
                raise _to_error(response)

            if attempt < max_retries:
                time.sleep(self._retry_delay(attempt, None))
                continue
            raise last_error

        raise last_error or APIConnectionError()


def _parse_json(response: httpx.Response) -> Any:
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def _to_error(response: httpx.Response):
    try:
        body = response.json()
    except ValueError:
        body = None
    headers = {k.lower(): v for k, v in response.headers.items()}
    return make_api_error(response.status_code, body, response.text, headers)


def _looks_like_jwt(key: str) -> bool:
    return key.startswith("ey") and key.count(".") == 2


def unwrap_data(body: Any) -> Any:
    """Native envelopes wrap payloads as {"data": ...}; OpenAI route returns raw."""
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body
