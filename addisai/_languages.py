"""Supported languages per modality, shared by every resource."""
import re
from typing import Dict, Literal, Tuple

from ._exceptions import AddisAIError

#: Languages supported for speech generation (``voice.generate``, ``voice.estimate``, batches, the voice catalog).
#: ``"am"`` Amharic, ``"om"`` Afaan Oromo, ``"ti"`` Tigrinya, ``"sw"`` Swahili, ``"ha"`` Hausa, ``"sid"`` Sidama
#: and ``"wal"`` Wolaytta.
VoiceLanguage = Literal["am", "om", "ti", "sw", "ha", "sid", "wal"]
VOICE_LANGUAGES = ("am", "om", "ti", "sw", "ha", "sid", "wal")

#: Languages supported for streamed speech (``voice.stream``) and real-time sessions (``realtime``): since 0.14.0 the
#: same seven as :data:`VoiceLanguage`.
RealtimeLanguage = Literal["am", "om", "ti", "sw", "ha", "sid", "wal"]
REALTIME_LANGUAGES = ("am", "om", "ti", "sw", "ha", "sid", "wal")

#: Languages supported by the deprecated legacy audio endpoint (``legacy.audio``).
LegacyLanguage = Literal["am", "om", "ti"]
LEGACY_VOICE_LANGUAGES = ("am", "om", "ti")

#: The public voices of each language, default first. The API is the source of truth (``voices.list``); this
#: mirror lets you check an ID offline. Every ID is ``<language>-<name>``.
VOICES: Dict[str, Tuple[str, ...]] = {
    "am": ("am-hamen", "am-simon", "am-yohanes-calm", "am-tesfa", "am-muaz", "am-roba", "am-nejat", "am-loza",
           "am-nahom", "am-amanuel", "am-tewodros", "am-kaleb", "am-dawit", "am-meron", "am-makda", "am-feven",
           "am-melat", "am-dibora", "am-sara"),
    "om": ("om-bikila", "om-ayyaantuu", "om-leensaa", "om-hawi", "om-diriba", "om-leta", "om-ebba", "om-chala",
           "om-obse"),
    "ti": ("ti-berhane", "ti-senait", "ti-haben", "ti-rahel", "ti-filimon", "ti-danait", "ti-yonas"),
    "sw": ("sw-rashid", "sw-neema", "sw-hassan", "sw-bakari", "sw-amina", "sw-juma", "sw-zainab"),
    "ha": ("ha-mustapha", "ha-sani", "ha-usman", "ha-musa"),
    "sid": ("sid-tigist", "sid-desta", "sid-bereket", "sid-selam", "sid-alemu"),
    "wal": ("wal-tona", "wal-almaz", "wal-amado", "wal-gobe", "wal-hiwot"),
}

#: The default voice of each language.
DEFAULT_VOICES: Dict[str, str] = {language: voices[0] for language, voices in VOICES.items()}

#: Languages supported for chat, including attachments and audio input.
ChatLanguage = Literal["am", "om", "ti"]

#: Languages supported for speech-to-text.
SttLanguage = Literal["am", "om", "ti", "en", "ha", "sw"]

#: Languages supported by Addis Scribe (transcription, streaming, live sessions, long-audio jobs).
#: ``"am"`` Amharic (the default), ``"om"`` Afaan Oromo, ``"ti"`` Tigrinya, ``"ha"`` Hausa, ``"sid"`` Sidama,
#: ``"wal"`` Wolaytta, ``"sw"`` Swahili and ``"en"`` English. Every language but Amharic runs on the turbo backend only, and
#: Swahili has no speaker labels (``capabilities()["languages"]["sw"]["speakers"]`` is ``False``).
ScribeLanguage = Literal["am", "om", "ti", "ha", "sid", "wal", "sw", "en"]

#: Languages supported for translation.
TranslateLanguage = Literal["am", "om", "ti", "en"]

_NAMES = {"am": "am (Amharic)", "om": "om (Afaan Oromo)", "ti": "ti (Tigrinya)", "sw": "sw (Swahili)",
          "ha": "ha (Hausa)", "sid": "sid (Sidama)", "wal": "wal (Wolaytta)"}
_VOICE_ID = re.compile(r"^[a-z]{2,3}-[a-z0-9]+(?:-[a-z0-9]+)*$")


def _choices(codes: Tuple[str, ...]) -> str:
    names = [_NAMES[code] for code in codes]
    return ", ".join(names[:-1]) + ", or " + names[-1]


def validate_voice_language(value: object) -> None:
    if value not in VOICE_LANGUAGES:
        raise AddisAIError("Voice language must be " + _choices(VOICE_LANGUAGES) + ".")


def validate_realtime_language(value: object) -> None:
    if value not in REALTIME_LANGUAGES:
        raise AddisAIError("Streamed and real-time voice language must be " + _choices(REALTIME_LANGUAGES) + ".")


def validate_legacy_language(value: object) -> None:
    if value not in LEGACY_VOICE_LANGUAGES:
        raise AddisAIError("Legacy audio language must be " + _choices(LEGACY_VOICE_LANGUAGES)
                           + ". Use voice.generate for other languages.")


def validate_voice_id(voice_id: object, language: object) -> None:
    """A voice ID is ``<language>-<name>`` and must belong to the request's language (``"sid-tigist"`` with
    ``language="sid"``). IDs that are not in :data:`VOICES` (new or private voices) still pass; the API decides."""
    if not isinstance(voice_id, str) or not _VOICE_ID.match(voice_id):
        raise AddisAIError('voice_id must look like "<language>-<name>", for example "ti-berhane".')
    if voice_id.split("-", 1)[0] != language:
        raise AddisAIError(f'voice_id "{voice_id}" is not a {language} voice. '
                           f'Use a "{language}-" voice such as "{DEFAULT_VOICES.get(str(language), language)}".')
