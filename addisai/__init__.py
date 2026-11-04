"""Official Addis AI SDK for Python."""
from ._client import AddisAI
from ._captions import to_srt, to_vtt
from ._clip import VoiceClip
from ._idempotency import ulid
from ._languages import (
    DEFAULT_VOICES,
    REALTIME_LANGUAGES,
    VOICE_LANGUAGES,
    VOICES,
    ChatLanguage,
    LegacyLanguage,
    RealtimeLanguage,
    ScribeLanguage,
    SttLanguage,
    TranslateLanguage,
    VoiceLanguage,
)
from ._streaming import AudioStream, ChatStream
from .resources.scribe import ScribeConnection, ScribeJobs, ScribeTranscriptStream, connect_scribe
from ._version import __version__
from .resources import ADDIS_CHAT_MODEL
from .resources.batches import to_batch_jsonl
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
    "RealtimeLanguage",
    "LegacyLanguage",
    "VOICE_LANGUAGES",
    "REALTIME_LANGUAGES",
    "VOICES",
    "DEFAULT_VOICES",
    "ChatLanguage",
    "ScribeLanguage",
    "SttLanguage",
    "TranslateLanguage",
    "ChatStream",
    "AudioStream",
    "RealtimeConnection",
    "ScribeConnection",
    "ScribeJobs",
    "ScribeTranscriptStream",
    "connect_scribe",
    "to_srt",
    "to_vtt",
    "connect_realtime",
    "decode_realtime_audio",
    "ulid",
    "ADDIS_CHAT_MODEL",
    "to_batch_jsonl",
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
