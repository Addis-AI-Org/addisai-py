"""Contract tests against the live public API with a real key. They spend a little credit (about 35 short
generations and 14 short transcriptions), so they run only when ``ADDIS_CONTRACT_API_KEY`` is set: by hand, or
from the manual ``contract`` workflow. Never point them at a load test."""
import io
import os
import wave

import pytest

from addisai import DEFAULT_VOICES, REALTIME_LANGUAGES, VOICE_LANGUAGES, VOICES, AddisAI, ulid

KEY = os.environ.get("ADDIS_CONTRACT_API_KEY")
pytestmark = pytest.mark.skipif(not KEY, reason="set ADDIS_CONTRACT_API_KEY to run live contract tests")

# Each text was checked by a round trip through Scribe in its language. Never shorter than ~12 letters:
# very short phrases can come out wrong.
TEXT = {
    "am": "ሰላም፣ እንኳን ወደ አዲስ ኤአይ በደህና መጡ።",
    "om": "Nagaa, gara Addis AI baga nagaan dhuftan.",
    "ti": "ሰላም፣ እንቋዕ ብደሓን መጻእኩም። ሎሚ ጽቡቕ መዓልቲ እዩ።",
    "sw": "Habari, karibu sana. Leo ni siku nzuri ya kujifunza kitu kipya pamoja.",
    "ha": "Barka da zuwa. Yau rana ce mai kyau don koyon sabon abu tare.",
    "sid": "Kunino babbaxxinno sidaamu budu tima, adonna shaanu babbaxxinno sidaamu budi sagale leeltawo yaate.",
    "wal": "Giyaa giddon daro asay shammes, baassi koshshiyabaa bayzzes.",
}
LAUNCH = ("ti", "sw", "ha", "sid", "wal")


@pytest.fixture(scope="module")
def addis():
    with AddisAI(api_key=KEY, base_url=os.environ.get("ADDIS_BASE_URL")) as client:
        yield client


@pytest.fixture(scope="module")
def speech(addis):
    """One 16 kHz clip per language from its default voice, reused as Scribe input: (WAV file, raw PCM)."""
    clips = {}
    for language in VOICE_LANGUAGES:
        clip = addis.voice.generate(voice_id=DEFAULT_VOICES[language], text=TEXT[language], language=language,
                                    output_format="pcm_16000")
        data = clip.content()
        with wave.open(io.BytesIO(data)) as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
            clips[language] = (data, wav.readframes(wav.getnframes()))
        assert len(clips[language][1]) > 32000, f"{language}: under one second of audio"
    return clips


@pytest.mark.parametrize("language", VOICE_LANGUAGES)
def test_catalog_matches_the_sdk_mirror(addis, language):
    live = [voice["id"] for voice in addis.voices.list(language=language) if voice.get("language") == language]
    assert set(live) == set(VOICES[language]), f"{language}: catalog drift"
    defaults = [voice["id"] for voice in addis.voices.list(language=language) if voice.get("is_default")]
    assert defaults == [DEFAULT_VOICES[language]]


@pytest.mark.parametrize("voice_id", [v for language in LAUNCH for v in VOICES[language]])
def test_every_launch_voice_synthesizes(addis, voice_id):
    language = voice_id.split("-", 1)[0]
    clip = addis.voice.generate(voice_id=voice_id, text=TEXT[language], language=language)
    assert (clip.voice_id, clip.language) == (voice_id, language)
    assert len(clip.content()) > 4000


@pytest.mark.parametrize("language", VOICE_LANGUAGES)
def test_upload_transcribes_each_language(addis, speech, language):
    result = addis.scribe.transcribe(audio=("speech.wav", speech[language][0], "audio/wav"), language=language,
                                     request_id=ulid())
    assert result["language"] == language
    assert result["text"].strip(), f"{language}: empty transcript"


@pytest.mark.parametrize("language", VOICE_LANGUAGES)
def test_live_session_transcribes_each_language(addis, speech, language):
    with addis.scribe.connect(language=language, request_id=ulid()) as live:
        audio = speech[language][1]
        for start in range(0, len(audio), 10240):  # 320 ms frames
            live.send_audio(audio[start:start + 10240])
        live.finish()
        for _ in live:
            pass
        assert live.completion["text"].strip(), f"{language}: empty live transcript"


@pytest.mark.parametrize("language", REALTIME_LANGUAGES)
def test_streaming_languages_stream(addis, language):
    audio = addis.voice.stream(voice_id=DEFAULT_VOICES[language], text=TEXT[language], language=language)
    assert len(audio.read()) > 4000
