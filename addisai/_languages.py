"""Supported languages per modality, shared by every resource."""
from typing import Literal

from ._exceptions import AddisAIError

#: Languages supported for speech generation (voice, real-time, legacy audio).
VoiceLanguage = Literal["am", "om", "ti"]
VOICE_LANGUAGES = ("am", "om", "ti")

#: Languages supported for chat, including attachments and audio input.
ChatLanguage = Literal["am", "om", "ti"]

#: Languages supported for speech-to-text.
SttLanguage = Literal["am", "om", "ti", "en", "ha", "sw"]

#: Languages supported by Addis Scribe (transcription, streaming, live sessions, long-audio jobs).
#: ``"om"`` (Afaan Oromo) runs on the turbo backend only.
ScribeLanguage = Literal["am", "om"]

#: Languages supported for translation.
TranslateLanguage = Literal["am", "om", "ti", "en"]


def validate_voice_language(value: object) -> None:
    if value not in VOICE_LANGUAGES:
        raise AddisAIError(
            "Voice language must be am (Amharic), om (Afaan Oromo), or ti (Tigrinya)."
        )
