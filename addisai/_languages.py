"""Supported voice languages, shared by all speech generation entry points."""
from typing import Literal

from ._exceptions import AddisAIError

VoiceLanguage = Literal["am", "om", "ti"]
VOICE_LANGUAGES = ("am", "om", "ti")


def validate_voice_language(value: object) -> None:
    if value not in VOICE_LANGUAGES:
        raise AddisAIError(
            "Voice language must be am (Amharic), om (Afaan Oromo), or ti (Tigrinya)."
        )
