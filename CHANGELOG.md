# Changelog

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
- **Chat / LLM:** OpenAI-compatible `chat.completions.create` with `system`,
  `persona`, tools/function calling, attachments, audio input; `chat.run_tools`
  agent loop; beta SSE streaming via `ChatStream`.
- **Speech-to-text:** `speech.transcribe`. **Translation:** `translate.create`.
- **Reliability/security:** automatic retries with backoff, idempotent paid
  calls, normalized exception hierarchy, secret redaction, Cloudflare-only
  transport. Built on `httpx`. Typed (`py.typed`).

> Persona, system prompts, and function calling depend on a backend rollout; they
> are verified and ready in the SDK and activate as the server side ships.
>
> An async client (`AsyncAddisAI`) is planned for a follow-up release.
