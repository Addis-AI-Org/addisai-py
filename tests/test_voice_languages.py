import json
import typing
from unittest.mock import Mock

import httpx
import pytest

from addisai import (DEFAULT_VOICES, REALTIME_LANGUAGES, VOICE_LANGUAGES, VOICES, AddisAI, AddisAIError,
                     RealtimeLanguage, VoiceLanguage, connect_realtime, to_batch_jsonl)

ALL_VOICES = [(language, voice_id) for language, voices in VOICES.items() for voice_id in voices]


def client(handler):
    return AddisAI(api_key="secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_language_constants_match_their_types():
    assert typing.get_args(VoiceLanguage) == VOICE_LANGUAGES == ("am", "om", "ti", "sw", "ha", "sid", "wal")
    assert typing.get_args(RealtimeLanguage) == REALTIME_LANGUAGES == VOICE_LANGUAGES
    assert set(VOICES) == set(VOICE_LANGUAGES)


def test_catalog_mirror_has_the_launch_voices_and_defaults():
    assert DEFAULT_VOICES == {"am": "am-hamen", "om": "om-bikila", "ti": "ti-berhane", "sw": "sw-rashid",
                              "ha": "ha-mustapha", "sid": "sid-tigist", "wal": "wal-tona"}
    assert VOICES["ha"] == ("ha-mustapha", "ha-sani", "ha-usman", "ha-musa")
    assert "ha-hauwa" not in VOICES["ha"]  # retired
    assert len(VOICES["sid"]) == len(VOICES["wal"]) == 5 and len(VOICES["ti"]) == len(VOICES["sw"]) == 7
    for language, voice_id in ALL_VOICES:
        assert voice_id.split("-", 1)[0] == language
    assert len({voice_id for _, voice_id in ALL_VOICES}) == len(ALL_VOICES)


@pytest.mark.parametrize("language", ["en", "fr", "unknown", "", None])
def test_unsupported_languages_never_call_http_or_open_a_socket(language):
    handler = Mock(return_value=httpx.Response(200, json={"data": []}))
    factory = Mock()
    with client(handler) as addis:
        params = {"language": language, "voice_id": "am-hamen", "text": "A complete sentence."}
        calls = [
            (r"Voice language", lambda: addis.voice.generate(**params)),
            (r"Streamed and real-time", lambda: addis.voice.stream(**params)),
            (r"Voice language", lambda: addis.voice.estimate(**params)),
            (r"Streamed and real-time", lambda: addis.realtime.create_session(voice_id="am-hamen", language=language)),
            (r"Streamed and real-time",
             lambda: addis.realtime.connect(voice_id="am-hamen", language=language, websocket_factory=factory)),
            (r"Legacy audio", lambda: addis.legacy.audio.generate(text=params["text"], language=language)),
            (r"Legacy audio", lambda: addis.legacy.audio.stream(text=params["text"], language=language)),
            (r"Voice language", lambda: addis.voices.list(language=language)),
            (r"Voice language", lambda: addis.voice.clips.list(language=language)),
            (r"Streamed and real-time", lambda: connect_realtime({"language": language}, websocket_factory=factory)),
        ]
        # None is the documented omitted filter value, but never a generation language.
        if language is None:
            calls = calls[:7] + calls[9:]
        for message, call in calls:
            with pytest.raises(AddisAIError, match=message):
                call()
        handler.assert_not_called()
        factory.assert_not_called()


def test_error_lists_every_voice_language():
    with client(Mock()) as addis, pytest.raises(AddisAIError) as error:
        addis.voice.generate(voice_id="en-emma", text="A complete sentence.", language="en")
    for name in ("am (Amharic)", "om (Afaan Oromo)", "ti (Tigrinya)", "sw (Swahili)", "ha (Hausa)", "sid (Sidama)",
                 "wal (Wolaytta)"):
        assert name in str(error.value)


@pytest.mark.parametrize("language,voice_id", ALL_VOICES)
def test_every_catalog_voice_generates_and_estimates(language, voice_id):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        assert (body["language"], body["voice_id"]) == (language, voice_id)
        calls.append(request.url.path)
        return httpx.Response(200, json={"data": {"id": "clip", "language": language, "voice_id": voice_id}})

    with client(handler) as addis:
        params = {"voice_id": voice_id, "language": language, "text": "A complete sentence."}
        assert addis.voice.generate(**params).voice_id == voice_id
        addis.voice.estimate(**params)
        to_batch_jsonl([{"custom_id": "a", **params}])
    assert calls == ["/api/v1/voice/generations", "/api/v1/voice/estimate"]


@pytest.mark.parametrize("language", REALTIME_LANGUAGES)
def test_realtime_languages_stream_and_open_sessions(language):
    voice_id = DEFAULT_VOICES[language]
    calls = []

    def handler(request):
        body = json.loads(request.content)
        assert (body["language"], body["voice_id"]) == (language, voice_id)
        calls.append(request.url.path)
        if request.url.path.endswith("/stream"):
            return httpx.Response(200, content=b'\0\0\0\0{"data":{"id":"clip","usage":{"credits_used":1}}}',
                                  headers={"X-Addis-Audio-Protocol": "mp3-frames-v1"})
        return httpx.Response(200, json={"data": {"token": "t", "language": language}})

    with client(handler) as addis:
        addis.voice.stream(voice_id=voice_id, language=language, text="A complete sentence.").read()
        addis.realtime.create_session(voice_id=voice_id, language=language)
    assert calls == ["/api/v1/voice/generations/stream", "/api/v1/realtime/sessions"]


@pytest.mark.parametrize("language,voice_id", [("sid", "wal-tona"), ("ti", "am-hamen"),
                                               ("sw", "Rashid"), ("wal", ""), ("sid", None), ("ha", "ha_musa")])
def test_voice_id_must_match_the_language(language, voice_id):
    handler = Mock()
    with client(handler) as addis:
        with pytest.raises(AddisAIError, match="voice_id"):
            addis.voice.generate(voice_id=voice_id, language=language, text="A complete sentence.")
        with pytest.raises(AddisAIError, match="voice_id"):
            to_batch_jsonl([{"custom_id": "a", "voice_id": voice_id, "language": language, "text": "x"}])
    handler.assert_not_called()


def test_catalog_filters_to_supported_languages():
    codes = ["am", "om", "ti", "sid", "wal", "ha", "sw", "en", "fr"]
    handler = lambda request: httpx.Response(200, json={"data": [{"id": code, "language": code} for code in codes]})
    with client(handler) as addis:
        assert [voice["language"] for voice in addis.voices.list()] == ["am", "om", "ti", "sid", "wal", "ha", "sw"]


@pytest.mark.parametrize("language", VOICE_LANGUAGES)
def test_catalog_lists_each_language(language):
    seen = []

    def handler(request):
        seen.append(request.url.params.get("language"))
        return httpx.Response(200, json={"data": [{"id": v, "language": language} for v in VOICES[language]]})

    with client(handler) as addis:
        assert [voice["id"] for voice in addis.voices.list(language=language)] == list(VOICES[language])
    assert seen == [language]


def test_ticket_without_language_cannot_open_socket():
    factory = Mock()
    with pytest.raises(AddisAIError, match="Streamed and real-time"):
        connect_realtime({"token": "ticket", "websocket_url": "wss://api.addisassistant.com/api/v1/realtime/voice"},
                         websocket_factory=factory)
    factory.assert_not_called()


def test_existing_clip_history_stays_accessible():
    history = [{"id": "historic", "language": "en", "voice_id": "older-voice"},
               {"id": "current", "language": "ti", "voice_id": "ti-berhane"}]
    handler = lambda request: httpx.Response(200, json={"data": history})
    with client(handler) as addis:
        assert [(clip.id, clip.language) for clip in addis.voice.clips.list()] == [("historic", "en"), ("current", "ti")]
