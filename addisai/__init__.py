"""Official Addis AI SDK for Python."""
from ._client import AddisAI
from ._clip import VoiceClip
from ._idempotency import ulid
from ._languages import VoiceLanguage
from ._streaming import AudioStream, ChatStream
from .resources.scribe import ScribeConnection, ScribeTranscriptStream, connect_scribe
from ._version import __version__
from .resources import ADDIS_CHAT_MODEL
from .resources.realtime import RealtimeConnection, connect_realtime, decode_realtime_audio
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
    "VoiceLanguage",
    "ChatStream",
    "AudioStream",
    "RealtimeConnection",
    "ScribeConnection",
    "ScribeTranscriptStream",
    "connect_scribe",
    "connect_realtime",
    "decode_realtime_audio",
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
