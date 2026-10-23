"""Files for the Batch API: inputs you upload, results and audio it writes."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Union

import httpx

from .._exceptions import AddisAIError, APIConnectionError
from .._transport import Options, Transport

#: Files at or below this size go in one multipart request.
DIRECT_UPLOAD_MAX_BYTES = 25 * 1024 * 1024
#: Largest batch input file the API accepts.
SIGNED_UPLOAD_MAX_BYTES = 100 * 1024 * 1024

FileContent = Union[bytes, str, "os.PathLike[str]"]


class Files:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def upload(
        self,
        file: FileContent,
        *,
        filename: Optional[str] = None,
        purpose: str = "batch_input",
        request_options: Optional[Options] = None,
    ) -> Dict[str, Any]:
        """Upload a batch input file (JSONL) from bytes or a path. Small files
        go in one request; larger ones (up to 100 MB) use a signed upload
        straight to storage. Returns the file once it is ready."""
        if isinstance(file, bytes):
            data = file
            name = filename or "input.jsonl"
        else:
            path = os.fspath(file)
            with open(path, "rb") as handle:
                data = handle.read()
            name = filename or os.path.basename(path)

        if len(data) > SIGNED_UPLOAD_MAX_BYTES:
            raise AddisAIError("Batch input files are limited to 100 MB. Split the batch.")

        if len(data) <= DIRECT_UPLOAD_MAX_BYTES:
            return self._transport.request(
                "POST",
                "/api/v1/files",
                data={"purpose": purpose},
                files={"file": (name, data, "application/jsonl")},
                options=request_options,
            )

        signed = self.create_signed_upload(
            filename=name, bytes=len(data), request_options=request_options
        )
        upload = signed["upload"]
        try:
            # No API key here: the signed URL carries its own authorization.
            response = self._transport.http_client.put(
                upload["url"], content=data, headers=upload.get("headers") or {}
            )
        except httpx.TransportError as exc:
            raise APIConnectionError("Upload to storage failed.", cause=exc) from exc
        if not response.is_success:
            raise AddisAIError(f"Upload to storage failed with status {response.status_code}.")
        return self.complete(signed["id"], request_options=request_options)

    def create_signed_upload(
        self,
        *,
        filename: str,
        bytes: int,
        content_type: str = "application/jsonl",
        request_options: Optional[Options] = None,
    ) -> Dict[str, Any]:
        """Start a signed upload. The result's ``upload`` holds the PUT URL."""
        return self._transport.request(
            "POST",
            "/api/v1/files",
            json={
                "purpose": "batch_input",
                "filename": filename,
                "bytes": bytes,
                "content_type": content_type,
            },
            options=request_options,
        )

    def complete(self, file_id: str, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        return self._transport.request(
            "POST", f"/api/v1/files/{file_id}/complete", options=request_options
        )

    def retrieve(self, file_id: str, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        return self._transport.request("GET", f"/api/v1/files/{file_id}", options=request_options)

    def delete(self, file_id: str, *, request_options: Optional[Options] = None) -> Dict[str, Any]:
        return self._transport.request("DELETE", f"/api/v1/files/{file_id}", options=request_options)

    def content_url(self, file_id: str, *, request_options: Optional[Options] = None) -> str:
        """A signed download URL, valid for about five minutes."""
        response = self._transport.request(
            "GET",
            f"/api/v1/files/{file_id}/content",
            raw=True,
            allow_redirect=True,
            options=request_options,
        )
        location = response.headers.get("location")
        if not location:
            raise AddisAIError("The file download link was not returned.")
        return location

    def content(self, file_id: str, *, request_options: Optional[Options] = None) -> bytes:
        """Download a file's bytes (result JSONL, error JSONL or generated audio)."""
        url = self.content_url(file_id, request_options=request_options)
        try:
            response = self._transport.http_client.get(url)
        except httpx.TransportError as exc:
            raise APIConnectionError("Download from storage failed.", cause=exc) from exc
        if not response.is_success:
            raise AddisAIError(f"Download from storage failed with status {response.status_code}.")
        return response.content
