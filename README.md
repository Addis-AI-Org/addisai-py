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

Use a matching language and voice ID for speech generation. Fetch the current
catalog with `voices.list` to choose another available voice.

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
