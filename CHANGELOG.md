# Changelog

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
