from __future__ import annotations

import json
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx


class ChatGenerationError(ValueError):
    """A credential-safe model failure suitable for logs and operator UI."""


class _ChatGenerationTransportError(ChatGenerationError):
    """A request transport failure that is safe to retry once."""


class _InvalidStructuredOutputError(ChatGenerationError):
    """A successful provider response that did not honor the JSON contract."""

    def __init__(self, raw_content: str) -> None:
        super().__init__("generation provider returned invalid structured output")
        self.raw_content = raw_content[:16000]


JSON_OUTPUT_REMINDER = (
    "OUTPUT FORMAT REMINDER (protocol instruction, not a visitor message; do not "
    "use it for language detection): Return exactly one valid JSON object matching the "
    "schema required by the system message. Output JSON only: no markdown fences, "
    "headings, explanations, or prose outside the JSON object. Re-check every field "
    "and all grounding rules before responding."
)
JSON_REPAIR_INSTRUCTION = (
    "This is a protocol instruction, not a visitor message and must not change the "
    "required response language. Your previous response did not honor the required "
    "JSON output contract. "
    "Re-evaluate it under every system safety, evidence, language, and grounding "
    "rule; do not merely wrap the prose. If approved evidence is empty, do not claim "
    "that this merchant or its catalog has or does not have a product. Return exactly "
    "one valid JSON object matching the schema required by the system message. "
    "Output JSON only, with no markdown or prose outside it."
)


@dataclass(frozen=True, slots=True)
class ChatGenerationIdentity:
    provider: str
    model_name: str


@dataclass(frozen=True, slots=True)
class ChatGenerationResult:
    content: str
    data: dict[str, Any]
    finish_reason: str | None
    usage: dict[str, int]
    transport_mode: str = "BUFFERED"
    first_delta_ms: int | None = None
    duration_ms: int | None = None


class ChatGenerationProvider(Protocol):
    identity: ChatGenerationIdentity

    def generate_json(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> ChatGenerationResult: ...


def chat_completions_endpoint(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ChatGenerationError("generation Base URL must be an HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ChatGenerationError("generation Base URL must not contain credentials")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def _json_object(value: str) -> dict[str, Any]:
    normalized = value.strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        normalized = "\n".join(lines).strip()
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError as exc:
        start = normalized.find("{")
        end = normalized.rfind("}")
        if start < 0 or end <= start:
            raise _InvalidStructuredOutputError(value) from exc
        try:
            payload = json.loads(normalized[start : end + 1])
        except json.JSONDecodeError as nested:
            raise _InvalidStructuredOutputError(value) from nested
    if not isinstance(payload, dict):
        raise _InvalidStructuredOutputError(value)
    return payload


def _messages_with_json_reminder(
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    if messages and messages[-1].get("content") == JSON_OUTPUT_REMINDER:
        return messages
    return [*messages, {"role": "user", "content": JSON_OUTPUT_REMINDER}]


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            str(block.get("text") or "")
            for block in value
            if isinstance(block, dict)
        )
    return ""


def _response_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ChatGenerationError(
            "generation provider returned an invalid response"
        ) from exc


def _result_from_body(
    body: Any,
    *,
    transport_mode: str = "BUFFERED",
    first_delta_ms: int | None = None,
    duration_ms: int | None = None,
) -> ChatGenerationResult:
    try:
        choice = body["choices"][0]
        content = _content_text(choice["message"]["content"])
        finish_reason = (
            str(choice.get("finish_reason"))
            if choice.get("finish_reason") is not None
            else None
        )
        raw_usage = body.get("usage") or {}
        usage = {
            str(key): int(value)
            for key, value in raw_usage.items()
            if isinstance(value, (int, float))
        }
    except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise ChatGenerationError(
            "generation provider returned an invalid response"
        ) from exc
    return ChatGenerationResult(
        content=content,
        data=_json_object(content),
        finish_reason=finish_reason,
        usage=usage,
        transport_mode=transport_mode,
        first_delta_ms=first_delta_ms,
        duration_ms=duration_ms,
    )


class OpenAICompatibleChatGeneration:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout_seconds: float = 45,
        max_output_tokens: int = 2048,
        temperature: float = 0.1,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise ChatGenerationError("generation API key is required")
        if not model_name.strip():
            raise ChatGenerationError("generation model is required")
        if timeout_seconds < 1 or timeout_seconds > 180:
            raise ChatGenerationError("generation timeout must be between 1 and 180 seconds")
        if max_output_tokens < 128 or max_output_tokens > 32768:
            raise ChatGenerationError(
                "generation max output tokens must be between 128 and 32768"
            )
        if temperature < 0 or temperature > 2:
            raise ChatGenerationError("generation temperature must be between 0 and 2")
        self._api_key = api_key.strip()
        self._endpoint = chat_completions_endpoint(base_url)
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._client = client or httpx.Client()
        self.identity = ChatGenerationIdentity(
            provider="openai-compatible",
            model_name=model_name.strip(),
        )

    def _request(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            return self._client.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise _ChatGenerationTransportError(
                "generation provider request timed out"
            ) from exc
        except httpx.HTTPError as exc:
            raise _ChatGenerationTransportError(
                "generation provider request failed"
            ) from exc

    def _request_with_transient_retry(
        self,
        payload: dict[str, Any],
    ) -> httpx.Response:
        """Retry one transient model failure; generation has no external write effect."""

        last_error: ChatGenerationError | None = None
        for attempt in range(2):
            try:
                response = self._request(payload)
            except ChatGenerationError as exc:
                last_error = exc
                if attempt == 0:
                    continue
                raise
            if attempt == 0 and (
                response.status_code == 429 or response.status_code >= 500
            ):
                continue
            return response
        assert last_error is not None
        raise last_error

    def _stream_request(
        self,
        payload: dict[str, Any],
    ) -> tuple[int, ChatGenerationResult | None]:
        started_at = time.perf_counter()
        try:
            with self._client.stream(
                "POST",
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=payload,
                timeout=self._timeout_seconds,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    response.read()
                    return response.status_code, None

                # Some compatible gateways ignore stream=true and return the normal
                # JSON envelope. Accept it without weakening response validation.
                content_type = response.headers.get("content-type", "").casefold()
                if "text/event-stream" not in content_type:
                    response.read()
                    return response.status_code, _result_from_body(
                        _response_json(response),
                        duration_ms=max(
                            0,
                            round((time.perf_counter() - started_at) * 1000),
                        ),
                    )

                content_parts: list[str] = []
                event_data: list[str] = []
                finish_reason: str | None = None
                usage: dict[str, int] = {}
                first_delta_ms: int | None = None

                def consume_event() -> bool:
                    nonlocal finish_reason, first_delta_ms, usage
                    if not event_data:
                        return False
                    raw_event = "\n".join(event_data).strip()
                    event_data.clear()
                    if raw_event == "[DONE]":
                        return True
                    if not raw_event:
                        return False
                    try:
                        event = json.loads(raw_event)
                    except json.JSONDecodeError as exc:
                        raise ChatGenerationError(
                            "generation provider returned an invalid stream"
                        ) from exc
                    if not isinstance(event, dict):
                        return False
                    raw_usage = event.get("usage") or {}
                    if isinstance(raw_usage, dict):
                        usage = {
                            str(key): int(value)
                            for key, value in raw_usage.items()
                            if isinstance(value, (int, float))
                        }
                    choices = event.get("choices") or []
                    if not isinstance(choices, list) or not choices:
                        return False
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        return False
                    delta = choice.get("delta") or {}
                    text_delta = (
                        _content_text(delta.get("content"))
                        if isinstance(delta, dict)
                        else ""
                    )
                    # A few gateways send a full message in their final SSE event.
                    if not text_delta and isinstance(choice.get("message"), dict):
                        text_delta = _content_text(choice["message"].get("content"))
                    if text_delta:
                        if first_delta_ms is None:
                            first_delta_ms = max(
                                0,
                                round((time.perf_counter() - started_at) * 1000),
                            )
                        content_parts.append(text_delta)
                    if choice.get("finish_reason") is not None:
                        finish_reason = str(choice["finish_reason"])
                        return True
                    # Some gateways hold the SSE connection open long after their
                    # upstream has completed. A fully parseable JSON object is a
                    # deterministic terminal condition for this structured API.
                    if text_delta and "}" in text_delta:
                        try:
                            _json_object("".join(content_parts))
                        except ChatGenerationError:
                            pass
                        else:
                            finish_reason = "structured_output_complete"
                            return True
                    return False

                for line in response.iter_lines():
                    if line == "":
                        if consume_event():
                            break
                    elif line.startswith("data:"):
                        event_data.append(line[5:].lstrip())
                if event_data:
                    consume_event()
        except httpx.TimeoutException as exc:
            raise _ChatGenerationTransportError(
                "generation provider request timed out"
            ) from exc
        except httpx.HTTPError as exc:
            raise _ChatGenerationTransportError(
                "generation provider request failed"
            ) from exc

        content = "".join(content_parts)
        return 200, ChatGenerationResult(
            content=content,
            data=_json_object(content),
            finish_reason=finish_reason,
            usage=usage,
            transport_mode="STREAM",
            first_delta_ms=first_delta_ms,
            duration_ms=max(
                0,
                round((time.perf_counter() - started_at) * 1000),
            ),
        )

    def _stream_request_with_transient_retry(
        self,
        payload: dict[str, Any],
    ) -> tuple[int, ChatGenerationResult | None]:
        """Retry one safe stream attempt before any answer is published."""

        last_error: _ChatGenerationTransportError | None = None
        for attempt in range(2):
            try:
                status_code, result = self._stream_request(payload)
            except _ChatGenerationTransportError as exc:
                last_error = exc
                if attempt == 0:
                    continue
                raise
            if attempt == 0 and (status_code == 429 or status_code >= 500):
                continue
            return status_code, result
        assert last_error is not None
        raise last_error

    def _buffered_json_request(
        self,
        payload: dict[str, Any],
        *,
        started_at: float,
        transport_mode: str = "BUFFERED",
    ) -> ChatGenerationResult:
        response = self._request_with_transient_retry(payload)
        # A few otherwise-compatible gateways do not implement response_format.
        # Retry only that validation class, never authentication or server failures.
        if response.status_code in {400, 404, 422}:
            payload = {
                key: value
                for key, value in payload.items()
                if key != "response_format"
            }
            response = self._request_with_transient_retry(payload)
        if response.status_code < 200 or response.status_code >= 300:
            raise ChatGenerationError(
                f"generation provider returned HTTP {response.status_code}"
            )
        return _result_from_body(
            _response_json(response),
            transport_mode=transport_mode,
            duration_ms=max(
                0,
                round((time.perf_counter() - started_at) * 1000),
            ),
        )

    def _repair_invalid_structured_output(
        self,
        *,
        messages: list[dict[str, str]],
        invalid: _InvalidStructuredOutputError,
        max_output_tokens: int,
        started_at: float,
        transport_mode: str,
    ) -> ChatGenerationResult:
        repair_messages = [
            *messages,
            {"role": "assistant", "content": invalid.raw_content},
            {"role": "user", "content": JSON_REPAIR_INSTRUCTION},
        ]
        return self._buffered_json_request(
            {
                "model": self.identity.model_name,
                "messages": repair_messages,
                "temperature": 0.0,
                "max_tokens": max_output_tokens,
                "response_format": {"type": "json_object"},
            },
            started_at=started_at,
            transport_mode=transport_mode,
        )

    def generate_json(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> ChatGenerationResult:
        if not messages:
            raise ChatGenerationError("generation messages are required")
        started_at = time.perf_counter()
        output_tokens = (
            self._max_output_tokens
            if max_output_tokens is None
            else max_output_tokens
        )
        request_messages = _messages_with_json_reminder(messages)
        payload: dict[str, Any] = {
            "model": self.identity.model_name,
            "messages": request_messages,
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": output_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            return self._buffered_json_request(
                payload,
                started_at=started_at,
            )
        except _InvalidStructuredOutputError as invalid:
            return self._repair_invalid_structured_output(
                messages=request_messages,
                invalid=invalid,
                max_output_tokens=output_tokens,
                started_at=started_at,
                transport_mode="BUFFERED_REPAIR",
            )

    def generate_json_stream(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> ChatGenerationResult:
        if not messages:
            raise ChatGenerationError("generation messages are required")
        started_at = time.perf_counter()
        output_tokens = (
            self._max_output_tokens
            if max_output_tokens is None
            else max_output_tokens
        )
        request_messages = _messages_with_json_reminder(messages)
        payload: dict[str, Any] = {
            "model": self.identity.model_name,
            "messages": request_messages,
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": output_tokens,
            "response_format": {"type": "json_object"},
            "stream": True,
        }
        try:
            status_code, result = self._stream_request_with_transient_retry(
                payload
            )
        except _InvalidStructuredOutputError as invalid:
            return self._repair_invalid_structured_output(
                messages=request_messages,
                invalid=invalid,
                max_output_tokens=output_tokens,
                started_at=started_at,
                transport_mode="STREAM_REPAIR",
            )
        if status_code in {400, 404, 422}:
            payload.pop("response_format", None)
            try:
                status_code, result = self._stream_request_with_transient_retry(
                    payload
                )
            except _InvalidStructuredOutputError as invalid:
                return self._repair_invalid_structured_output(
                    messages=request_messages,
                    invalid=invalid,
                    max_output_tokens=output_tokens,
                    started_at=started_at,
                    transport_mode="STREAM_REPAIR",
                )
        if result is None and status_code in {400, 404, 422}:
            # Preserve availability for older OpenAI-compatible gateways while
            # making the transport downgrade visible in the returned trace.
            return self.generate_json(
                messages=request_messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
        if result is None:
            raise ChatGenerationError(
                f"generation provider returned HTTP {status_code}"
            )
        return result


@lru_cache(maxsize=8)
def openai_compatible_chat_provider(
    *,
    api_key: str,
    base_url: str,
    model_name: str,
    timeout_seconds: float,
    max_output_tokens: int,
    temperature: float,
) -> OpenAICompatibleChatGeneration:
    return OpenAICompatibleChatGeneration(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
    )
