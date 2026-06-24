"""Chat / LLM resource (OpenAI-compatible, with system, persona, tools)."""
from __future__ import annotations

import json as _json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from .._exceptions import AddisAIError
from .._streaming import ChatStream
from .._transport import Options, Transport

#: Public model id surfaced to developers. Never the underlying model.
ADDIS_CHAT_MODEL = "addis-1-alef"


class Chat:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self.completions = Completions(transport)

    def run_tools(
        self,
        *,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        language: str = "am",
        system: Optional[str] = None,
        persona: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_tool_roundtrips: int = 5,
        request_options: Optional[Options] = None,
    ) -> Dict[str, Any]:
        """Automatic tool-calling loop. Each tool's ``function`` dict must include
        a ``callable`` key with the local implementation."""
        impls: Dict[str, Callable[[Any], Any]] = {}
        wire_tools: List[Dict[str, Any]] = []
        for tool in tools:
            fn = tool["function"]
            impls[fn["name"]] = fn["callable"]
            wire_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": fn["name"],
                        "description": fn.get("description"),
                        "parameters": fn.get("parameters"),
                    },
                }
            )

        convo = list(messages)
        for i in range(max_tool_roundtrips + 1):
            completion = self.completions.create(
                messages=convo,
                tools=wire_tools,
                language=language,
                system=system,
                persona=persona,
                temperature=temperature,
                max_tokens=max_tokens,
                request_options=request_options,
            )
            choice = completion["choices"][0]
            calls = choice["message"].get("tool_calls") or []
            if not calls or choice.get("finish_reason") != "tool_calls":
                return completion
            if i == max_tool_roundtrips:
                raise AddisAIError(
                    f"run_tools exceeded max_tool_roundtrips ({max_tool_roundtrips}) without a final answer."
                )
            convo.append(choice["message"])
            for call in calls:
                name = call["function"]["name"]
                impl = impls.get(name)
                if impl is None:
                    raise AddisAIError(f'No implementation provided for tool "{name}".')
                raw_args = call["function"].get("arguments") or "{}"
                try:
                    args = _json.loads(raw_args)
                except ValueError:
                    args = raw_args
                result = impl(args)
                convo.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "name": name,
                        "content": result if isinstance(result, str) else _json.dumps(result),
                    }
                )
        raise AddisAIError("run_tools terminated unexpectedly.")


class Completions:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def create(
        self,
        *,
        messages: List[Dict[str, Any]],
        language: str = "am",
        model: Optional[str] = None,  # accepted for compatibility; not sent
        system: Optional[str] = None,
        persona: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        stream: bool = False,
        attachments: Optional[List[Any]] = None,
        audio: Optional[Any] = None,
        request_options: Optional[Options] = None,
    ):
        """Create a chat completion. Returns a dict (OpenAI shape), or a
        :class:`ChatStream` when ``stream=True``."""
        if stream:
            if attachments or audio:
                raise AddisAIError("Streaming is not supported with attachments or audio input.")
            if tools or any(m.get("role") == "tool" or m.get("tool_calls") for m in messages):
                raise AddisAIError("Streaming is not supported with tool calling. Use non-streaming mode for tools.")
            body = _build_native_body(messages, language, system, persona, temperature, max_tokens, tools, tool_choice, stream=True)
            return ChatStream(self._transport, body, options=request_options)

        if attachments or audio:
            return self._create_multipart(
                messages, language, system, persona, temperature, max_tokens, tools, tool_choice, attachments, audio, request_options
            )

        # The model is selected by the backend and is intentionally not forwarded.
        # The deployed backend reads `prompt`/`conversation_history`, not `messages`.
        body = _build_native_body(messages, language, system, persona, temperature, max_tokens, tools, tool_choice)
        envelope = self._transport.request(
            "POST", "/api/v1/chat_generate", json=body, options=request_options
        )
        native = envelope.get("data", {}) if isinstance(envelope, dict) else {}
        return _native_to_openai(native)

    def _create_multipart(
        self, messages, language, system, persona, temperature, max_tokens, tools, tool_choice, attachments, audio, request_options
    ) -> Dict[str, Any]:
        files: Dict[str, Any] = {}
        attachment_field_names: List[str] = []
        for idx, att in enumerate(attachments or []):
            field = f"attachment_{idx}"
            files[field] = att if isinstance(att, tuple) else (field, att, "application/octet-stream")
            attachment_field_names.append(field)
        if audio is not None:
            files["chat_audio_input"] = audio if isinstance(audio, tuple) else ("audio.wav", audio, "audio/wav")

        request_data = _build_native_body(messages, language, system, persona, temperature, max_tokens, tools, tool_choice)
        if attachment_field_names:
            request_data["attachment_field_names"] = attachment_field_names

        data = {"request_data": _json.dumps(request_data)}
        envelope = self._transport.request(
            "POST", "/api/v1/chat_generate", files=files, data=data, options=request_options
        )
        native = envelope.get("data", {}) if isinstance(envelope, dict) else {}
        return _native_to_openai(native)


def _build_native_body(
    messages: List[Dict[str, Any]],
    language: str,
    system: Optional[str],
    persona: Optional[str],
    temperature: Optional[float],
    max_tokens: Optional[int],
    tools: Optional[List[Dict[str, Any]]],
    tool_choice: Optional[Any],
    stream: bool = False,
) -> Dict[str, Any]:
    """Convert OpenAI-style messages into the backend's native chat request
    (``prompt`` + ``conversation_history`` + folded ``system``)."""
    system_parts: List[str] = []
    if system:
        system_parts.append(system)
    non_system: List[Dict[str, Any]] = []
    for m in messages:
        if m.get("role") in ("system", "developer"):
            content = m.get("content")
            if isinstance(content, str) and content.strip():
                system_parts.append(content)
        else:
            non_system.append(m)

    last_user = -1
    for i in range(len(non_system) - 1, -1, -1):
        m = non_system[i]
        if m.get("role") == "user" and isinstance(m.get("content"), str) and m["content"].strip():
            last_user = i
            break

    prompt = non_system[last_user]["content"] if last_user >= 0 else None
    history_source = non_system[:last_user] if last_user >= 0 else non_system
    conversation_history = [
        {"role": "assistant" if m.get("role") in ("assistant", "tool") else "user", "content": m.get("content")}
        for m in history_source
        if isinstance(m.get("content"), str) and m.get("content")
    ]

    body: Dict[str, Any] = {"target_language": language}
    if prompt is not None:
        body["prompt"] = prompt
    if conversation_history:
        body["conversation_history"] = conversation_history
    if system_parts:
        body["system"] = "\n\n".join(system_parts)
    if persona:
        body["persona"] = persona
    if tools is not None:
        body["tools"] = tools
    if tool_choice is not None:
        body["tool_choice"] = tool_choice

    gen: Dict[str, Any] = {}
    if temperature is not None:
        gen["temperature"] = temperature
    if max_tokens is not None:
        gen["maxOutputTokens"] = max_tokens
    if stream:
        gen["stream"] = True
    if gen:
        body["generation_config"] = gen
    return body


def _normalize_finish(reason: Any) -> str:
    if not isinstance(reason, str) or not reason:
        return "stop"
    mapping = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter", "RECITATION": "content_filter", "TOOL_CALLS": "tool_calls"}
    return mapping.get(reason.upper(), reason.lower())


def _native_to_openai(data: Dict[str, Any]) -> Dict[str, Any]:
    tool_calls = data.get("tool_calls") or None
    message: Dict[str, Any] = (
        {"role": "assistant", "content": data.get("response_text") or None, "tool_calls": tool_calls}
        if tool_calls
        else {"role": "assistant", "content": data.get("response_text") or ""}
    )
    usage_meta = data.get("usage_metadata") or {}
    completion = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": ADDIS_CHAT_MODEL,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else _normalize_finish(data.get("finish_reason")),
            }
        ],
        "usage": {
            "prompt_tokens": usage_meta.get("prompt_token_count", 0),
            "completion_tokens": usage_meta.get("candidates_token_count", 0),
            "total_tokens": usage_meta.get("total_token_count", 0),
        }
        if usage_meta
        else None,
    }
    if data.get("transcription_raw") or data.get("transcription_clean"):
        completion["transcription"] = {
            "raw": data.get("transcription_raw"),
            "clean": data.get("transcription_clean"),
        }
    if data.get("uploaded_attachments"):
        completion["uploaded_attachments"] = data["uploaded_attachments"]
    return completion
