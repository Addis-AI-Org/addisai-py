# Changelog

## 0.10.0

- **Scribe jobs can be cancelled:** `scribe.jobs.cancel(request_id)` (`DELETE /api/v1/scribe/jobs/{id}`). Nothing is
  charged. An upload or queued job is removed and its request ID is free again; a processing job is stopped and
  ends failed with `REQUEST_CANCELLED` (its request ID stays used); a finished job is `409 JOB_FINISHED`.
- `transcribe_long` cancels its own job on `KeyboardInterrupt` (Ctrl-C) before the upload is complete, so an interrupted call no longer holds one of the account's two
  long-file slots. Once the job is queued, an interrupt only stops the waiting (`recover` reads the result later).

## 0.9.0

- **Batches:** `batches.create_from_requests([...])` uploads many text to speech
  requests at once; they run off-peak and finish within 24 hours at half the
  standard price. Also `batches.create`, `retrieve`, `list` (auto-paginating),
  `cancel`, `requests`, `results` (parsed result and error lines) and `wait_for`.
- **Files:** `files.upload` (bytes or a path; one request up to 25 MB, signed
  upload up to 100 MB), `create_signed_upload`, `complete`, `retrieve`, `delete`,
  `content_url` and `content`. Downloads follow the signed storage link without
  sending your API key.
- **Batches support Tigrinya:** every request in `create_from_requests` takes `language` `"am"`, `"om"` or `"ti"` with a
  matching voice ID (for Tigrinya: `ti-berhane`, `ti-senait`, `ti-haben`, `ti-rahel`, `ti-filimon`, `ti-danait`,
  `ti-yonas`). Other languages raise `AddisAIError` locally before any upload, exactly as `voice.generate` does.
- **Scribe long audio (up to three hours):** `scribe.transcribe_long(audio=..., speakers=..., timestamps=..., request_id=..., on_progress=...)` transcribes a file of up to three hours (512 MB) as a job and returns the settled result in the same shape as `transcribe` plus `chunks`. `audio` is `bytes`, a seekable binary file object, a path (`str` or `os.PathLike`) or a `(filename, data, content_type)` tuple. A file of at most 95 MiB goes up in one request; a larger one is declared and sent as 4 MiB parts read from disk in order, skipping parts the server already holds and sending a part again after a connection error. The result is polled every 5 seconds (honouring `Retry-After`) for up to four hours; `on_progress` receives each progress dict (`audio_seconds`, `processed_seconds`, `chunks`). Jobs default to `timestamps="word"`, run on the turbo backend only, and are never retried on paid steps; interrupted callers use `scribe.recover(request_id)`.
- **`scribe.jobs`** (`ScribeJobs`, exported): the steps behind `transcribe_long`, each returning the API's `data` dict: `upload(audio=...)` (one request), `create(request_id=..., bytes=...)` (declaration), `put_part(request_id, index, data)`, `complete(request_id)`, `status(request_id)` and `wait(request_id, on_progress=..., poll_seconds=5, timeout=14400)`.
- `Transport.request` accepts `content=bytes`, sent as `application/octet-stream`.

## 0.8.1

- Tigrinya (`ti`) is documented and typed across every modality it supports: voice generation and real-time sessions (seven native voices, `ti-berhane` by default), chat including attachments and audio input, speech-to-text and translation.
- New typing aliases exported from `addisai`: `ChatLanguage`, `SttLanguage` and `TranslateLanguage`. `chat.completions.create`, `chat.run_tools`, `speech.transcribe` and `translate.create` use them instead of plain `str`. Runtime behaviour is unchanged.
- Tests cover the Tigrinya wire format for chat (`target_language`), speech-to-text (`language_code`) and translation (`source_language`/`target_language`). Addis Scribe remains Amharic-only.

## 0.8.0

- Scribe: longer audio. Uploads up to one hour and 95 MB (speaker labels included); live sessions up to 15 minutes (the limit comes from the server's `session.created`, no longer fixed at 180 seconds in the SDK).
- `scribe.transcribe` waits for long files: when the API answers that the upload is still processing, the SDK polls `recover` every 5 seconds until the result is ready (up to an hour).

## 0.7.0

- Scribe: `backend` now defaults to `"turbo"` in `transcribe`, `stream`, `create_session` and `connect`. Turbo is the faster mode, takes many requests at once and costs the same per character. Pass `backend="standard"` to keep the previous behaviour.

## 0.6.0

- **Scribe speaker labels:** `scribe.transcribe(backend="turbo", speakers=True)`
  adds `speaker` (1-based number, or `None` when a word could not be attributed) to
  every word and segment, and a `speakers` count to the result. The default
  `speakers=False` sends no `speakers` parameter. Speaker labels require
  `backend="turbo"` and turn on word timestamps; other backends and `scribe.stream()`
  reject `speakers=True` locally.
- **Captions:** `to_srt()` prefixes labelled cues with `Speaker N: ` (counted toward
  the 42-character line limit) and `to_vtt()` opens them with a `<v Speaker N>` voice
  span. Segments without a speaker are formatted exactly as in 0.5.0.

## 0.5.0

- **Scribe word timestamps:** `scribe.transcribe(timestamps="word")` returns
  `words` and caption-ready `segments` (seconds from the start of the file). The
  default `timestamps="none"` sends no `timestamps` parameter.
  `scribe.stream()` rejects `timestamps="word"` locally.
- **Caption helpers:** top-level `addisai.to_srt()` and `addisai.to_vtt()` format
  `segments` locally (42 characters per line, at most 2 lines) and raise
  `AddisAIError` when segments are missing.
- **Scribe backends are now `"standard"` and `"turbo"`** (default `"standard"`).
  Other values fail locally without an API request.

## 0.4.0

- **Addis Scribe (Amharic transcription):** `addis.scribe.transcribe()` for file
  uploads, `stream()` for provisional text followed by a settled completion,
  `connect()` and `create_session()` for live PCM audio with scoped one-use
  tickets (plus `connect_scribe()`), `usage()` for wallet balance and rate,
  `recover()` for settled results by request ID, and `capabilities()` for limits.
- Backends `"standard"` (default) and `"turbo"`, 320ms/1120ms chunks, stable
  request IDs, and no automatic retries on paid uploads or ticket issuance.

## 0.3.1

- Present Amharic, Afaan Oromo, and Tigrinya together with real catalog voices:
  Hamen, Bikila, and Berhane, and their matching voice IDs.
- Place real-time streaming under Voice and keep License as the final section.
- Choose an available voice matching the requested language in the runnable
  real-time example when no voice ID is supplied.
- Restrict voice types and runtime requests to `am`, `om`, and `ti`, including
  HTTP streaming, WebSocket session creation and connection, and deprecated audio
  generation. Filter the discoverable catalog to those languages.
- Preserve existing clip history, non-voice language support, dependencies, and
  billing protocol. Previously accepted voice codes outside these three now fail
  locally without an API request.

## 0.3.0

- Enable billed `voice.stream()` with MP3 phrase decoding, clip/usage metadata,
  truncation errors, and idempotent clip recovery.
- Add `realtime.create_session()`, `realtime.connect()`, and `connect_realtime()`
  with scoped, short-lived WebSocket tickets, text/audio events, and MP3 `speak()`.
- Add text buffering and cancellation; started synthesis still completes billing.
- Add the optional `realtime` extra for Python WebSocket connections.
- Document real-time voice integration in Amharic, Afaan Oromo, and Tigrigna.

## 0.2.0

- **Voice 2 billing:** preserve the production minute-pricing fields on voice
  estimates, usage responses, and generated clips.
- **Voice examples:** use the production `am-hamen` voice ID.

## 0.1.1

- **Docs:** correct the homepage/brand link to `https://addisassistant.com`
  (was a placeholder domain). No code changes.

## 0.1.0 — Developer preview

Initial release of the official Addis AI SDK for Python.

- **Voice (TTS):** `voice.generate`, `voices.list/preview`, `voice.estimate`,
  `voice.usage`, `voice.clips.*`, `VoiceClip` helpers.
- **Chat / LLM:** familiar `chat.completions.create` with `system`,
  `persona`, tools/function calling, attachments, audio input; `chat.run_tools`
  agent loop; beta SSE streaming via `ChatStream`.
- **Speech-to-text:** `speech.transcribe`. **Translation:** `translate.create`.
- **Reliability/security:** automatic retries with backoff, idempotent paid
  calls, normalized exception hierarchy, secret redaction, Addis API-only
  transport. Built on `httpx`. Typed (`py.typed`).

> Persona, system prompts, and function calling depend on a backend rollout; they
> are verified and ready in the SDK and activate as the server side ships.
>
> An async client (`AsyncAddisAI`) is planned for a follow-up release.
