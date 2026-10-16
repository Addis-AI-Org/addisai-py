"""Batch API: many requests at once, run off-peak within 24 hours at half price."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional

from .._exceptions import AddisAIError
from .._idempotency import ulid
from .._transport import Options, Transport
from .files import Files

TERMINAL_STATUSES = frozenset({"completed", "failed", "expired", "cancelled"})


def to_batch_jsonl(requests: Iterable[Dict[str, Any]]) -> str:
    """JSONL for a text to speech batch. Each request is a dict with
    ``custom_id``, ``text``, ``voice_id``, ``language`` and optionally
    ``output_format`` (default ``"mp3_44100"``) and ``voice_settings``."""
    seen = set()
    lines = []
    for request in requests:
        custom_id = request["custom_id"]
        if custom_id in seen:
            raise AddisAIError(f'custom_id "{custom_id}" is used twice.')
        seen.add(custom_id)
        body: Dict[str, Any] = {
            "text": request["text"],
            "voice_id": request["voice_id"],
            "language": request["language"],
            "output_format": request.get("output_format", "mp3_44100"),
        }
        if request.get("voice_settings"):
            body["voice_settings"] = request["voice_settings"]
        lines.append(json.dumps({"custom_id": custom_id, "body": body}, ensure_ascii=False))
    if not lines:
        raise AddisAIError("A batch needs at least one request.")
    return "\n".join(lines) + "\n"


class Batches:
    def __init__(self, transport: Transport, files: Files) -> None:
        self._transport = transport
        self._files = files

    def create(
        self,
        *,
        input_file_id: str,
        endpoint: str = "/v1/voice/generations",
        completion_window: str = "24h",
        metadata: Optional[Dict[str, str]] = None,
        request_options: Optional[Options] = None,
    ) -> Dict[str, Any]:
        """Create a batch from an uploaded JSONL file. An idempotency key is
        generated when you do not pass one and reused across automatic retries,
        so a retry never creates a second batch."""
        options = dict(request_options or {})
        options.setdefault("idempotency_key", ulid())
        return self._transport.request(
            "POST",
            "/api/v1/batches",
            json={
                "input_file_id": input_file_id,
                "endpoint": endpoint,
                "completion_window": completion_window,
                "metadata": metadata or {},
            },
            options=options,
        )

    def create_from_requests(
        self,
        requests: Iterable[Dict[str, Any]],
        *,
        metadata: Optional[Dict[str, str]] = None,
        filename: str = "batch.jsonl",
        request_options: Optional[Options] = None,
    ) -> Dict[str, Any]:
        """Write the requests as JSONL, upload them, and create the batch."""
        data = to_batch_jsonl(requests).encode("utf-8")
        file = self._files.upload(data, filename=filename, request_options=request_options)
        return self.create(
            input_file_id=file["id"], metadata=metadata, request_options=request_options
        )

    def retrieve(self, batch_id: str, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        return self._transport.request("GET", f"/api/v1/batches/{batch_id}", options=request_options)

    def list(
        self,
        *,
        limit: Optional[int] = None,
        after: Optional[str] = None,
        request_options: Optional[Options] = None,
    ) -> "BatchPage":
        """Newest first. Iterate the result to walk every page."""

        def fetch(cursor: Optional[str]) -> Dict[str, Any]:
            return self._transport.request(
                "GET",
                "/api/v1/batches",
                query={"limit": limit, "after": cursor},
                options=request_options,
            )

        return BatchPage(fetch, fetch(after), _next_batch_cursor)

    def cancel(self, batch_id: str, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        """Queued requests stop; running ones finish and are billed."""
        return self._transport.request(
            "POST", f"/api/v1/batches/{batch_id}/cancel", options=request_options
        )

    def requests(
        self,
        batch_id: str,
        *,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        request_options: Optional[Options] = None,
    ) -> "BatchPage":
        """Per-request status, ordered by input line."""

        def fetch(cursor: Optional[str]) -> Dict[str, Any]:
            return self._transport.request(
                "GET",
                f"/api/v1/batches/{batch_id}/requests",
                query={"status": status, "limit": limit, "after": cursor},
                options=request_options,
            )

        return BatchPage(fetch, fetch(None), _next_line_cursor)

    def results(
        self, batch_id: str, *, request_options: Optional[Options] = None
    ) -> Iterator[Dict[str, Any]]:
        """Every result line (successes, then failures), parsed. Empty until
        the batch has finished and written its files."""
        batch = self.retrieve(batch_id, request_options=request_options)
        for file_id in (batch.get("output_file_id"), batch.get("error_file_id")):
            if not file_id:
                continue
            text = self._files.content(file_id, request_options=request_options).decode("utf-8")
            for line in text.splitlines():
                if line.strip():
                    yield json.loads(line)

    def wait_for(
        self,
        batch_id: str,
        *,
        poll_interval: float = 30.0,
        timeout: Optional[float] = None,
        request_options: Optional[Options] = None,
        _sleep: Callable[[float], None] = time.sleep,
    ) -> Dict[str, Any]:
        """Poll until the batch is completed, failed, expired or cancelled."""
        interval = max(poll_interval, 5.0)
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            batch = self.retrieve(batch_id, request_options=request_options)
            if batch.get("status") in TERMINAL_STATUSES:
                return batch
            if deadline is not None and time.monotonic() + interval > deadline:
                raise AddisAIError(f"Batch {batch_id} is still {batch.get('status')}.")
            _sleep(interval)


def _next_batch_cursor(page: Dict[str, Any]) -> Optional[str]:
    return page.get("last_id") if page.get("has_more") else None


def _next_line_cursor(page: Dict[str, Any]) -> Optional[str]:
    rows = page.get("data") or []
    return str(rows[-1]["line"]) if page.get("has_more") and rows else None


class BatchPage:
    """Iterable that auto-paginates; ``data`` is the first page only."""

    def __init__(
        self,
        fetch: Callable[[Optional[str]], Dict[str, Any]],
        first: Dict[str, Any],
        next_cursor: Callable[[Dict[str, Any]], Optional[str]],
    ) -> None:
        self._fetch = fetch
        self._first = first
        self._next_cursor = next_cursor

    @property
    def data(self) -> List[Dict[str, Any]]:
        return list(self._first.get("data") or [])

    @property
    def has_more(self) -> bool:
        return bool(self._first.get("has_more"))

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        page = self._first
        while True:
            for item in page.get("data") or []:
                yield item
            cursor = self._next_cursor(page)
            if not cursor:
                return
            page = self._fetch(cursor)
