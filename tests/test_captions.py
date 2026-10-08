import httpx
import pytest
from addisai import AddisAI, AddisAIError, to_srt, to_vtt

RAW = {"text": "ሰላም", "request_id": "stable", "seconds": 1, "compute_ms": 5, "backend": "standard", "chunk": "1120ms", "mode": "offline", "model": "addis-scribe-streaming", "usage": {"record_id": "ledger", "characters": 3, "price_per_1000_characters": 3.5, "credits_used": .0105, "credits_remaining": 9.9895, "currency": "ETB", "settled": True}}
SEGMENT = {"text": "ሰላም ወዳጆቻችን እንዴት ከረማችሁ ዛሬ እንግዲህ እንግዳ አድርጌ ያቀረኩላችሁ", "start": 18.8, "end": 21.8}

def client(handler):
    return AddisAI(api_key="test-secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

def test_standard_backend_default_and_timestamps_sent_only_when_set():
    seen = []
    def handler(request):
        seen.append(request.url.params)
        return httpx.Response(200, json={"data": RAW})
    addis = client(handler)
    addis.scribe.transcribe(audio=b"a", request_id="a")
    addis.scribe.transcribe(audio=b"a", request_id="b", backend="turbo", timestamps="word")
    assert seen[0]["backend"] == "standard"
    assert "timestamps" not in seen[0]
    assert seen[1]["backend"] == "turbo"
    assert seen[1]["timestamps"] == "word"

@pytest.mark.parametrize("backend", ["fast", "default", ""])
def test_unknown_backends_fail_before_http(backend):
    calls = []
    addis = client(lambda r: calls.append(r) or httpx.Response(200, json={"data": RAW}))
    with pytest.raises(AddisAIError, match="backend"):
        addis.scribe.transcribe(audio=b"a", backend=backend)
    with pytest.raises(AddisAIError, match="backend"):
        addis.scribe.create_session(backend=backend)
    with pytest.raises(AddisAIError, match="timestamps"):
        addis.scribe.transcribe(audio=b"a", timestamps="segment")
    assert calls == []

def test_stream_rejects_word_timestamps_locally():
    calls = []
    addis = client(lambda r: calls.append(r) or httpx.Response(200, json={"data": RAW}))
    with pytest.raises(AddisAIError, match=r"completed uploads.*transcribe\("):
        addis.scribe.stream(audio=b"a", timestamps="word")
    assert calls == []

def test_words_and_segments_surface_in_result():
    words = [{"text": "ሰላም", "start": 18.9, "end": 19.52}]
    addis = client(lambda r: httpx.Response(200, json={"data": {**RAW, "words": words, "segments": [SEGMENT]}}))
    result = addis.scribe.transcribe(audio=b"a", timestamps="word")
    assert result["words"] == words
    assert result["segments"] == [SEGMENT]
    assert "00:00:18,800 --> 00:00:21,800" in to_srt(result)

def test_srt_exact_amharic_wrap():
    assert to_srt({"segments": [SEGMENT]}) == "1\n00:00:18,800 --> 00:00:21,800\nሰላም ወዳጆቻችን እንዴት ከረማችሁ ዛሬ እንግዲህ እንግዳ አድርጌ\nያቀረኩላችሁ\n"

def test_vtt_exact():
    assert to_vtt({"segments": [SEGMENT]}) == "WEBVTT\n\n00:00:18.800 --> 00:00:21.800\nሰላም ወዳጆቻችን እንዴት ከረማችሁ ዛሬ እንግዲህ እንግዳ አድርጌ\nያቀረኩላችሁ\n"

def test_numbered_cues_blank_lines_and_two_line_cap():
    long = "ሀ" * 50
    segments = [{"text": "ሰላም", "start": 0, "end": 0.83},
                {"text": long + " ቃል " + "በ" * 40 + " ሌላ ቃል", "start": 3725.4567, "end": 3727}]
    tail = "ቃል " + "በ" * 40 + " ሌላ ቃል"
    assert to_srt({"segments": segments}) == "1\n00:00:00,000 --> 00:00:00,830\nሰላም\n\n2\n01:02:05,457 --> 01:02:07,000\n" + long + "\n" + tail + "\n"
    assert to_vtt({"segments": segments}) == "WEBVTT\n\n00:00:00.000 --> 00:00:00.830\nሰላም\n\n01:02:05.457 --> 01:02:07.000\n" + long + "\n" + tail + "\n"

def test_missing_segments_raise():
    with pytest.raises(AddisAIError, match='timestamps="word"'):
        to_srt({})
    with pytest.raises(AddisAIError, match="segments"):
        to_vtt({"segments": None})
