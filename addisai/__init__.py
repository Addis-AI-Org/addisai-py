"""Official Addis AI SDK for Python."""
from ._client import AddisAI
from ._clip import VoiceClip
from ._idempotency import ulid
from ._streaming import AudioStream, ChatStream
from ._version import __version__
from .resources import ADDIS_CHAT_MODEL
from ._exceptions import (
    AddisAIError,
    APIConnectionError,
    APIConnectionTimeoutError,
    APIError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    GenerationInProgressError,
    IdempotencyConflictError,
    InsufficientCreditsError,
    InternalServerError,
    NotFoundError,
    NotSupportedError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

__all__ = [
    "AddisAI",
    "VoiceClip",
    "ChatStream",
    "AudioStream",
    "ulid",
    "ADDIS_CHAT_MODEL",
    "__version__",
    "AddisAIError",
    "APIError",
    "APIConnectionError",
    "APIConnectionTimeoutError",
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "GenerationInProgressError",
    "IdempotencyConflictError",
    "InsufficientCreditsError",
    "InternalServerError",
    "NotFoundError",
    "NotSupportedError",
    "PermissionDeniedError",
    "RateLimitError",
    "UnprocessableEntityError",
]
