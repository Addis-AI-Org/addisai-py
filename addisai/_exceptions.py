"""Unified exception hierarchy, normalized from every backend envelope shape."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class AddisAIError(Exception):
    """Base class for all SDK errors (including config/usage errors)."""


class NotSupportedError(AddisAIError):
    """A capability exists in the SDK surface but is not yet enabled."""


class APIConnectionError(AddisAIError):
    def __init__(self, message: str = "Connection error.", cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


class APIConnectionTimeoutError(APIConnectionError):
    def __init__(self, message: str = "Request timed out.") -> None:
        super().__init__(message)


class APIError(AddisAIError):
    """Any non-2xx HTTP response."""

    def __init__(
        self,
        status: int,
        message: str,
        *,
        code: Optional[str] = None,
        details: Optional[List[Dict[str, Any]]] = None,
        request_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details or []
        self.request_id = request_id
        self.headers = headers or {}

    def _header_int(self, name: str) -> Optional[int]:
        raw = self.headers.get(name.lower())
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None


class BadRequestError(APIError):  # 400
    pass


class AuthenticationError(APIError):  # 401
    pass


class InsufficientCreditsError(APIError):  # 402
    @property
    def available_balance(self) -> Optional[float]:
        for d in self.details:
            if d.get("code") == "balance_too_low":
                import re

                nums = re.findall(r"\d+(?:\.\d+)?", d.get("message", ""))
                if nums:
                    return float(nums[-1])
        return None


class PermissionDeniedError(APIError):  # 403
    pass


class NotFoundError(APIError):  # 404
    pass


class ConflictError(APIError):  # 409
    pass


class IdempotencyConflictError(ConflictError):  # 409 IDEMPOTENCY_CONFLICT
    pass


class GenerationInProgressError(ConflictError):  # 409 GENERATION_IN_PROGRESS
    @property
    def retry_after(self) -> Optional[int]:
        return self._header_int("retry-after")


class UnprocessableEntityError(APIError):  # 413 / 422
    pass


class RateLimitError(APIError):  # 429
    @property
    def retry_after(self) -> Optional[int]:
        return self._header_int("retry-after")

    @property
    def limit(self) -> Optional[int]:
        return self._header_int("x-ratelimit-limit")

    @property
    def remaining(self) -> Optional[int]:
        return self._header_int("x-ratelimit-remaining")

    @property
    def reset(self) -> Optional[int]:
        return self._header_int("x-ratelimit-reset")


class InternalServerError(APIError):  # >= 500
    pass


def _parse_envelope(status: int, body: Any, raw_text: str) -> Dict[str, Any]:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return {
                "message": err.get("message") or f"Request failed with status {status}.",
                "code": err.get("code") or err.get("type"),
                "details": err.get("details") if isinstance(err.get("details"), list) else [],
            }
        if isinstance(body.get("message"), str):
            return {"message": body["message"], "code": body.get("code"), "details": []}
    return {
        "message": (raw_text or "")[:500] or f"Request failed with status {status}.",
        "code": None,
        "details": [],
    }


def make_api_error(status: int, body: Any, raw_text: str, headers: Dict[str, str]) -> APIError:
    parsed = _parse_envelope(status, body, raw_text)
    code = parsed["code"]
    upper = (code or "").upper()
    request_id = headers.get("x-request-id") or headers.get("cf-ray")
    kwargs = dict(code=code, details=parsed["details"], request_id=request_id, headers=headers)
    message = parsed["message"]

    if status == 400:
        return BadRequestError(status, message, **kwargs)
    if status == 401:
        return AuthenticationError(status, message, **kwargs)
    if status == 402:
        return InsufficientCreditsError(status, message, **kwargs)
    if status == 403:
        return PermissionDeniedError(status, message, **kwargs)
    if status == 404:
        return NotFoundError(status, message, **kwargs)
    if status == 409:
        if upper == "IDEMPOTENCY_CONFLICT":
            return IdempotencyConflictError(status, message, **kwargs)
        if upper == "GENERATION_IN_PROGRESS":
            return GenerationInProgressError(status, message, **kwargs)
        return ConflictError(status, message, **kwargs)
    if status in (413, 422):
        return UnprocessableEntityError(status, message, **kwargs)
    if status == 429:
        return RateLimitError(status, message, **kwargs)
    if status >= 500:
        return InternalServerError(status, message, **kwargs)
    return APIError(status, message, **kwargs)
