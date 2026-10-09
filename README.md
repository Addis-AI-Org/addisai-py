# addisai (Python)

The official [Addis AI](https://addisassistant.com) SDK for Python — voice (text‑to‑speech), chat/LLM with system prompts, personas and function calling, speech‑to‑text, and translation, with examples for **Amharic (`am`)**, **Afaan Oromo (`om`)**, and **Tigrinya (`ti`)**.

Mirrors the [Node.js SDK](https://github.com/Addis-AI-Org/addisai-js) surface, Pythonic and `snake_case`.

```bash
pip install addisai
```

Requires Python 3.8+.

## Quickstart

```python
from addisai import AddisAI

addis = AddisAI()  # reads ADDIS_API_KEY from the environment

# Text-to-speech
clip = addis.voice.generate(voice_id="am-hamen", text="ሰላም ለዓለም።", language="am")
clip.to_file("welcome.mp3")

# Chat
res = addis.chat.completions.create(
    language="am",
    system="Answer in concise bullet points.",
    messages=[{"role": "user", "content": "ስለ አዲስ አበባ ንገረኝ"}],
)
print(res["choices"][0]["message"]["content"])
```

## Configuration

```python
addis = AddisAI(
    api_key="...",        # or set ADDIS_API_KEY
    timeout=60.0,          # seconds (voice.generate raises this to >= 95s)
    max_retries=2,         # backoff on 408/409/425/429/5xx
)
```

The key is read from `api_key=` or `ADDIS_API_KEY`, never logged, and redacted in `repr()`. The SDK only talks to the Cloudflare‑wrapped API and refuses raw `*.supabase.co` hosts.

## Languages

| Language | Code | Example voice | Voice ID |
| --- | --- | --- | --- |
| Amharic | `am` | Hamen | `am-hamen` |
| Afaan Oromo | `om` | Bikila | `om-bikila` |
| Tigrinya | `ti` | Berhane | `ti-berhane` |

Voice generation and real-time sessions support these three languages. Other
language codes are rejected locally before any API request or socket connection.
Use a matching language and voice ID. `voices.list` returns this three-language
catalog so you can choose another available voice.

## Voice (text‑to‑speech)

```python
clip = addis.voice.generate(
    voice_id="am-hamen",
    text="ሰላም።",
    language="am",
    output_format="mp3_44100",                 # mp3_44100 | wav_44100 | pcm_16000
    voice_settings={"speed": 50, "stability": 50, "similarity": 50, "style": 0},
)
clip.audio_url
clip.usage          # {"credits_used": ..., "currency": "ETB", ...}
data = clip.content()   # bytes
clip.to_file("out.mp3")
```

Idempotency keys are generated automatically and reused across retries so a retry is never double‑billed. Pass `client_request_id=` for full control.

```python
addis.voices.list(language="am", gender="female")
addis.voice.estimate(voice_id="am-hamen", text="ሰላም", language="am")
addis.voice.usage()
for clip in addis.voice.clips.list(language="am"):  # auto-paginates
    print(clip.id)
addis.voice.clips.delete("clip_123")
```

### Real-time voice

```python
from uuid import uuid4

# Select a matching pair from the Languages table.
voice_id, language = "ti-berhane", "ti"
text = "ሰላም፣ እንቋዕ ናብ ኣዲስ ኤኣይ ብደሓን መጻእኩም።"

# HTTP streaming: no extra dependency needed.
audio = addis.voice.stream(
    voice_id=voice_id, language=language, text=text,
    client_request_id=str(uuid4()),
)
audio.to_file("speech.mp3")
print(audio.metadata["usage"])

# Persistent sockets: pip install "addisai[realtime]"
with addis.realtime.connect(voice_id=voice_id, language=language) as voice:
    with open("speech.mp3", "wb") as output:
        for chunk in voice.speak(text, str(uuid4())):
            output.write(chunk)
    print(voice.last_completion["usage"])
```

`realtime.create_session()` creates a scoped, one-use ticket valid for 60 seconds;
`connect_realtime(ticket)` opens its socket without a developer key. Keep keys on
your application server. Sessions last up to 10 minutes, allow one utterance at
a time, and carry a cumulative text budget of up to 5,000 characters. Cancellation
mutes delivery; an already-started synthesis completes and is billed.

Use `append()` and `commit()` to buffer a complete generated utterance before
synthesis. For early WAV pieces, select `audio_format="wav_mp3"`, iterate raw
`audio.delta` events and use `decode_realtime_audio(event)`; play each piece
according to its `format`. `speak()` yields concatenatable MP3 and requires an
`mp3` session. Use any matching voice and language pair from the Languages table.
HTTP streams support MP3 only. Keep request IDs stable when recovering a failed
request in a new session to avoid a second charge; use a fresh ID for each new
utterance.

See [examples/realtime.py](examples/realtime.py).

Run the same example with any of the documented languages:

```bash
ADDIS_VOICE_LANGUAGE=am ADDIS_VOICE_ID=am-hamen python examples/realtime.py "ሰላም፣ እንኳን ወደ አዲስ ኤአይ በደህና መጡ።"
ADDIS_VOICE_LANGUAGE=om ADDIS_VOICE_ID=om-bikila python examples/realtime.py "Nagaa, gara Addis AI baga nagaan dhuftan."
ADDIS_VOICE_LANGUAGE=ti ADDIS_VOICE_ID=ti-berhane python examples/realtime.py "ሰላም፣ እንቋዕ ናብ ኣዲስ ኤኣይ ብደሓን መጻእኩም።"
```

## Chat / LLM

```python
res = addis.chat.completions.create(
    language="am",
    system="Be concise.",
    persona="You are RecipeBot by AcmeCorp.",
    messages=[{"role": "user", "content": "የእንጀራ አሰራር አስተምረኝ"}],
    temperature=0.7,
    max_tokens=1200,
)
```

> The model is selected by Addis AI; responses report the id `addis-1-alef`.

Chat accepts `am`, `om`, and `ti` for text, attachments, and audio input.

### Function calling

```python
def get_order_status(args):
    return {"status": "shipped", "eta": "tomorrow"}

final = addis.chat.run_tools(
    language="am",
    messages=[{"role": "user", "content": "Check order 123 and summarize it."}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "Fetch order status by order ID.",
            "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
            "callable": get_order_status,
        },
    }],
)
print(final["choices"][0]["message"]["content"])
```

### Streaming (beta)

`stream=True` returns a `ChatStream` — iterate for OpenAI‑style chunk dicts, or use the accumulators:

```python
stream = addis.chat.completions.create(
    language="am", messages=[{"role": "user", "content": "Capital?"}], stream=True
)
for chunk in stream:
    print(chunk["choices"][0]["delta"].get("content", ""), end="", flush=True)

# or, instead of iterating:
text = addis.chat.completions.create(language="am", messages=[...], stream=True).final_text()
completion = addis.chat.completions.create(language="am", messages=[...], stream=True).final_completion()
```

Streaming is beta and not available with tools.

## Addis Scribe

Scribe transcribes **Amharic**. Choose `backend="standard"` (default) or
`backend="turbo"`; both bill the same character rate.
Save a request ID before sending audio; recover it after an interrupted response.

```python
from addisai import AddisAI, ulid

request_id = ulid()
with AddisAI() as addis:
    with open("speech.wav", "rb") as audio:
        result = addis.scribe.transcribe(audio=audio, backend="standard", request_id=request_id)
    print(result["text"], result["usage"]["credits_used"])
    # Recovery returns the original settled result without another charge:
    # recovered = addis.scribe.recover(request_id)
    with open("speech.wav", "rb") as audio:
        with addis.scribe.stream(audio=audio, request_id=ulid()) as stream:
            for event in stream:
                if event["type"] == "transcript.partial":
                    print(event["text"])
                elif event["type"] == "transcript.completed":
                    print(event["data"]["usage"])
```

### Word timestamps and captions

Pass `timestamps="word"` to `transcribe()` to receive `words` and caption-ready
`segments` (times in seconds from the start of the file). Timestamps cost nothing
extra. `addisai.to_srt()` and `addisai.to_vtt()` format the segments locally, without
another API call, wrapping each cue at 42 characters per line and at most 2 lines.

```python
from addisai import AddisAI, to_srt, to_vtt, ulid

with AddisAI() as addis:
    with open("speech.wav", "rb") as audio:
        result = addis.scribe.transcribe(audio=audio, timestamps="word", request_id=ulid())
print(result["words"][0])  # {'text': 'ሰላም', 'start': 18.9, 'end': 19.52}
with open("speech.srt", "w", encoding="utf-8") as f:
    f.write(to_srt(result))
with open("speech.vtt", "w", encoding="utf-8") as f:
    f.write(to_vtt(result))
# 1
# 00:00:18,800 --> 00:00:21,800
# ሰላም ወዳጆቻችን እንዴት ከረማችሁ ዛሬ እንግዲህ እንግዳ አድርጌ
# ያቀረኩላችሁ
```

Timestamps are available for completed uploads only: `stream()` rejects
`timestamps="word"` locally, and live sessions do not return timestamps.
`to_srt()`/`to_vtt()` raise `AddisAIError` if the result has no `segments`; they also
work on the dict returned by `recover()` when the original request used timestamps.

#### Speaker labels

Pass `speakers=True` with `backend="turbo"` to label who is talking. It turns on
word timestamps, costs nothing extra, and adds a `speaker` number to every word and
segment plus a `speakers` count on the result. Speakers are numbered 1, 2, … in the
order they first talk; a word that could not be attributed has `speaker: None`.
A new caption cue starts whenever the speaker changes. `to_srt()` starts each labelled
cue with `Speaker N: `, and `to_vtt()` marks it with a `<v Speaker N>` voice tag.

```python
with AddisAI() as addis:
    with open("interview.wav", "rb") as audio:
        result = addis.scribe.transcribe(audio=audio, backend="turbo", speakers=True,
                                         request_id=ulid())
print(result["speakers"])  # 2
with open("interview.srt", "w", encoding="utf-8") as f:
    f.write(to_srt(result))
# 1
# 00:00:00,600 --> 00:00:01,600
# Speaker 1: ሰላም ወዳጆቻችን
#
# 2
# 00:00:01,700 --> 00:00:03,000
# Speaker 2: እንዴት ናችሁ
```

Good to know:

- Speaker labels need `backend="turbo"`; other backends fail locally before any
  request. `stream()` and live sessions do not support them.
- On simulated Amharic conversations, 97.8% of words got the right speaker.
- Labels work best with 2 to 4 people and get less accurate when people talk over
  each other.
- Labels are "Speaker 1", "Speaker 2" and so on, not names.

### Live audio

Install `pip install "addisai[realtime]"` for `addis.scribe.connect(request_id=...)`.
Read its event iterator while calling `send_audio(frame)` with **raw 16 kHz mono
PCM16 little-endian** (3,200 bytes per 100 ms), then call `finish()` and read the
settled completion. Send and receive concurrently for continuous microphone audio.
`completion` includes the final transcript and usage. `create_session` issues a
scoped one-use ticket; exported `connect_scribe(session)` opens that ticket's
socket without account credentials in its URL. `capabilities()` returns model
limits and `usage()` returns your wallet balance and current rate.

HTTP uploads accept 25 MiB / 180 seconds. File streams emit partials after upload;
WebSockets accept audio incrementally. HTTP defaults to standard/1120ms chunks; sockets
to standard/320ms. Tickets expire after 60 seconds. One request is admitted per wallet.
Only final transcript UTF-16 character units are billed; partials have no separate
charge. Paid requests/ticket creation are not automatically retried. Disconnecting
or closing a stream can still bill accepted audio. Recover settled results for 24
hours; pending settlement remains recoverable. New audio/settings need a new ID.

See the [Scribe guide](https://docs.addisassistant.com/docs/capabilities/speech-to-text)
for complete live PCM, recovery and billing examples.

## Speech‑to‑text & translation

```python
with open("call.wav", "rb") as f:
    t = addis.speech.transcribe(audio=f, language="am")  # am|om|ti|en|ha|sw
print(t["text"])

out = addis.translate.create(text="Hello", source="en", target="am")  # am|om|ti|en
print(out["text"])
```

Speech recognition uses `/api/v2/stt`; confidence may be `None`.

## Legacy audio (deprecated)

```python
# ⚠️ deprecated — use addis.voice.generate
out = addis.legacy.audio.generate(text="ሰላም", language="am")
out.to_file("legacy.wav")

# streaming bridge — yields audio bytes, handles both legacy encodings
audio = addis.legacy.audio.stream(text="ሰላም", language="am")
audio.to_file("legacy.wav")        # or: data = audio.read()
```

## Errors

```python
from addisai import InsufficientCreditsError, RateLimitError, APIError

try:
    addis.voice.generate(voice_id="am-hamen", text="ሰላም", language="am")
except InsufficientCreditsError as e:
    show_top_up(e.available_balance)
except RateLimitError as e:
    sleep(e.retry_after or 1)
except APIError as e:
    print(e.status, e.code, e.details)
```

## Not yet in the Python SDK

An async client (`AsyncAddisAI`) is the one planned follow‑up. Everything else — including streaming — is at parity with the Node SDK.

## Live smoke test

`scripts/smoke.py` exercises the real API end-to-end. It is **not** a PR gate —
the `smoke` workflow runs on manual dispatch and a daily schedule, only where the
repo secret `ADDIS_SMOKE_API_KEY` (a low-balance sandbox key) is set. Run locally
with `ADDIS_API_KEY=<key> python scripts/smoke.py`.

## License

MIT
