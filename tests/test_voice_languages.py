import json
from unittest.mock import Mock

import httpx
import pytest

from addisai import AddisAI, AddisAIError, connect_realtime


@pytest.mark.parametrize("language", ["sid", "wal", "ha", "sw", "en", "fr", "unknown", "", None])
def test_excluded_languages_never_call_http_or_open_a_socket(language):
    handler = Mock(return_value=httpx.Response(200, json={"data": []}))
    factory = Mock()
    with AddisAI(api_key="secret", http_client=httpx.Client(transport=httpx.MockTransport(handler))) as addis:
        params = {"language": language, "voice_id": "voice", "text": "A complete sentence."}
        calls = [
            lambda: addis.voice.generate(**params),
            lambda: addis.voice.stream(**params),
            lambda: addis.voice.estimate(**params),
            lambda: addis.realtime.create_session(voice_id="voice", language=language),
            lambda: addis.realtime.connect(voice_id="voice", language=language, websocket_factory=factory),
            lambda: addis.legacy.audio.generate(text=params["text"], language=language),
            lambda: addis.legacy.audio.stream(text=params["text"], language=language),
            lambda: addis.voices.list(language=language),
            lambda: addis.voice.clips.list(language=language),
            lambda: connect_realtime({"language": language}, websocket_factory=factory),
        ]
        # None is the documented omitted filter value, but never a generation language.
        if language is None:
            calls = calls[:7] + calls[9:]
        for call in calls:
            with pytest.raises(AddisAIError, match=r"am \(Amharic\), om \(Afaan Oromo\), or ti \(Tigrinya\)"):
                call()
        handler.assert_not_called()
        factory.assert_not_called()


@pytest.mark.parametrize("language,voice_id", [("am", "am-hamen"), ("om", "om-bikila"), ("ti", "ti-berhane")])
def test_approved_languages_use_matching_voice_in_modern_voice_calls(language, voice_id):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        assert body["language"] == language
        assert body["voice_id"] == voice_id
        calls.append(request.url.path)
        if request.url.path.endswith("/stream"):
            return httpx.Response(200, content=b'\0\0\0\0{"data":{"id":"clip","usage":{"credits_used":1}}}',
                                  headers={"X-Addis-Audio-Protocol": "mp3-frames-v1"})
        return httpx.Response(200, json={"data": {"id": "clip", "language": language, "voice_id": voice_id}})

    with AddisAI(api_key="secret", http_client=httpx.Client(transport=httpx.MockTransport(handler))) as addis:
        params = {"voice_id": voice_id, "language": language, "text": "A complete sentence."}
        addis.voice.generate(**params)
        addis.voice.stream(**params).read()
        addis.voice.estimate(**params)
        addis.realtime.create_session(voice_id=voice_id, language=language)
    assert calls == ["/api/v1/voice/generations", "/api/v1/voice/generations/stream",
                     "/api/v1/voice/estimate", "/api/v1/realtime/sessions"]


def test_wider_server_catalog_exposes_only_approved_languages():
    codes = ["am", "om", "ti", "sid", "wal", "ha", "sw", "en", "fr"]
    handler = lambda request: httpx.Response(200, json={"data": [{"id": code, "language": code} for code in codes]})
    with AddisAI(api_key="secret", http_client=httpx.Client(transport=httpx.MockTransport(handler))) as addis:
        assert [voice["language"] for voice in addis.voices.list()] == ["am", "om", "ti"]


def test_ticket_without_language_cannot_open_socket():
    factory = Mock()
    with pytest.raises(AddisAIError, match="Voice language"):
        connect_realtime({"token": "ticket", "websocket_url": "wss://api.addisassistant.com/api/v1/realtime/voice"},
                         websocket_factory=factory)
    factory.assert_not_called()


def test_existing_clip_history_stays_accessible():
    history = [{"id": "historic", "language": "en", "voice_id": "older-voice"},
               {"id": "current", "language": "ti", "voice_id": "ti-berhane"}]
    handler = lambda request: httpx.Response(200, json={"data": history})
    with AddisAI(api_key="secret", http_client=httpx.Client(transport=httpx.MockTransport(handler))) as addis:
        assert [(clip.id, clip.language) for clip in addis.voice.clips.list()] == [("historic", "en"), ("current", "ti")]
