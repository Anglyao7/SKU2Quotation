from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
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
    attempt_count: int = 1


class ChatGenerationProvider(Protocol):
    identity: ChatGenerationIdentity

    def generate_json(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> ChatGenerationResult: ...

    def generate_json_stream(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        on_answer_delta: Callable[[str], None] | None = None,
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


def _json_string_end(value: str, start: int) -> int | None:
    """Return the closing quote for one JSON string, or None if incomplete."""

    escaped = False
    for index in range(start + 1, len(value)):
        character = value[index]
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == '"':
            return index
    return None


def _json_string_field_start(value: str, field_name: str) -> int | None:
    """Find the first character of a top-level-compatible JSON string value.

    The generation contract is a single JSON object. Scanning complete JSON string
    tokens prevents an `answer` substring inside another value from being mistaken
    for the field name while still supporting chunks split at any byte boundary.
    """

    index = 0
    while index < len(value):
        if value[index] != '"':
            index += 1
            continue
        end = _json_string_end(value, index)
        if end is None:
            return None
        try:
            token = json.loads(value[index : end + 1])
        except json.JSONDecodeError:
            index = end + 1
            continue
        cursor = end + 1
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        if cursor >= len(value):
            return None
        if value[cursor] != ":":
            index = end + 1
            continue
        cursor += 1
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        if token != field_name:
            index = end + 1
            continue
        if cursor >= len(value):
            return None
        return cursor + 1 if value[cursor] == '"' else None
    return None


def _decode_json_string_prefix(value: str) -> tuple[str, bool]:
    """Decode the complete portion of a JSON string body without its first quote."""

    decoded: list[str] = []
    index = 0
    simple_escapes = {
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
    }
    while index < len(value):
        character = value[index]
        if character == '"':
            return "".join(decoded), True
        if character != "\\":
            decoded.append(character)
            index += 1
            continue
        if index + 1 >= len(value):
            break
        escape = value[index + 1]
        if escape in simple_escapes:
            decoded.append(simple_escapes[escape])
            index += 2
            continue
        if escape != "u" or index + 6 > len(value):
            break
        raw_codepoint = value[index + 2 : index + 6]
        try:
            codepoint = int(raw_codepoint, 16)
        except ValueError:
            break
        if 0xD800 <= codepoint <= 0xDBFF:
            if (
                index + 12 > len(value)
                or value[index + 6 : index + 8] != "\\u"
            ):
                break
            try:
                low = int(value[index + 8 : index + 12], 16)
            except ValueError:
                break
            if not 0xDC00 <= low <= 0xDFFF:
                break
            decoded.append(
                chr(0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00))
            )
            index += 12
            continue
        if 0xDC00 <= codepoint <= 0xDFFF:
            break
        decoded.append(chr(codepoint))
        index += 6
    return "".join(decoded), False


class IncrementalJSONTextField:
    """Extract newly decoded characters from one streamed JSON string field."""

    def __init__(self, field_name: str) -> None:
        self._field_name = field_name
        self._raw = ""
        self._value_start: int | None = None
        self._emitted_length = 0
        self._complete = False

    def feed(self, delta: str) -> str:
        if self._complete or not delta:
            return ""
        self._raw += delta
        if self._value_start is None:
            self._value_start = _json_string_field_start(
                self._raw,
                self._field_name,
            )
            if self._value_start is None:
                return ""
        decoded, self._complete = _decode_json_string_prefix(
            self._raw[self._value_start :]
        )
        if len(decoded) <= self._emitted_length:
            return ""
        fresh = decoded[self._emitted_length :]
        self._emitted_length = len(decoded)
        return fresh


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
        first_answer_timeout_seconds: float = 12,
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
        if (
            first_answer_timeout_seconds < 1
            or first_answer_timeout_seconds > 180
        ):
            raise ChatGenerationError(
                "generation first answer timeout must be between 1 and 180 seconds"
            )
        if max_output_tokens < 128 or max_output_tokens > 32768:
            raise ChatGenerationError(
                "generation max output tokens must be between 128 and 32768"
            )
        if temperature < 0 or temperature > 2:
            raise ChatGenerationError("generation temperature must be between 0 and 2")
        self._api_key = api_key.strip()
        self._endpoint = chat_completions_endpoint(base_url)
        self._timeout_seconds = timeout_seconds
        self._first_answer_timeout_seconds = min(
            timeout_seconds,
            first_answer_timeout_seconds,
        )
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
        *,
        on_answer_delta: Callable[[str], None] | None = None,
        read_timeout_seconds: float | None = None,
        total_timeout_seconds: float | None = None,
        first_answer_timeout_seconds: float | None = None,
    ) -> tuple[int, ChatGenerationResult | None]:
        started_at = time.perf_counter()
        answer_delta_seen = False
        answer_stream = (
            IncrementalJSONTextField("answer")
            if on_answer_delta is not None
            else None
        )

        def publish_answer_delta(raw_delta: str) -> None:
            nonlocal answer_delta_seen
            if answer_stream is None or on_answer_delta is None:
                return
            answer_delta = answer_stream.feed(raw_delta)
            if answer_delta:
                answer_delta_seen = True
                on_answer_delta(answer_delta)

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
                timeout=(
                    self._timeout_seconds
                    if read_timeout_seconds is None
                    else read_timeout_seconds
                ),
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    response.read()
                    return response.status_code, None

                # Some compatible gateways ignore stream=true and return the normal
                # JSON envelope. Accept it without weakening response validation.
                content_type = response.headers.get("content-type", "").casefold()
                if "text/event-stream" not in content_type:
                    response.read()
                    result = _result_from_body(
                        _response_json(response),
                        duration_ms=max(
                            0,
                            round((time.perf_counter() - started_at) * 1000),
                        ),
                    )
                    publish_answer_delta(result.content)
                    return response.status_code, result

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
                        publish_answer_delta(text_delta)
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
                    elapsed_seconds = time.perf_counter() - started_at
                    if (
                        total_timeout_seconds is not None
                        and elapsed_seconds > total_timeout_seconds
                    ):
                        raise _ChatGenerationTransportError(
                            "generation provider request timed out"
                        )
                    if (
                        first_answer_timeout_seconds is not None
                        and not answer_delta_seen
                        and elapsed_seconds > first_answer_timeout_seconds
                    ):
                        raise _ChatGenerationTransportError(
                            "generation provider first answer timed out"
                        )
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
        *,
        on_answer_delta: Callable[[str], None] | None = None,
    ) -> tuple[int, ChatGenerationResult | None]:
        """Retry one transient stream only when no answer has been published."""

        last_error: _ChatGenerationTransportError | None = None
        started_at = time.perf_counter()
        for attempt in range(2):
            attempt_started_at = time.perf_counter()
            elapsed_seconds = attempt_started_at - started_at
            remaining_seconds = self._timeout_seconds - elapsed_seconds
            if remaining_seconds <= 0:
                if last_error is not None:
                    raise last_error
                raise _ChatGenerationTransportError(
                    "generation provider request timed out"
                )
            first_answer_remaining_seconds = (
                self._first_answer_timeout_seconds - elapsed_seconds
            )
            if (
                on_answer_delta is not None
                and first_answer_remaining_seconds <= 0
            ):
                if last_error is not None:
                    raise last_error
                raise _ChatGenerationTransportError(
                    "generation provider first answer timed out"
                )
            answer_published = False

            def publish(delta: str) -> None:
                nonlocal answer_published
                answer_published = True
                if on_answer_delta is not None:
                    on_answer_delta(delta)

            try:
                status_code, result = self._stream_request(
                    payload,
                    on_answer_delta=(publish if on_answer_delta is not None else None),
                    # A dead first connection previously consumed the complete
                    # 45-second model timeout before the safe retry even began.
                    # Cap the first attempt's no-data read window. Explicit
                    # first-answer and total deadlines below also stop gateways
                    # extending the request with heartbeats or hidden reasoning.
                    read_timeout_seconds=(
                        min(
                            remaining_seconds,
                            first_answer_remaining_seconds,
                        )
                        if on_answer_delta is not None
                        else remaining_seconds
                    ),
                    total_timeout_seconds=remaining_seconds,
                    first_answer_timeout_seconds=(
                        min(
                            remaining_seconds,
                            first_answer_remaining_seconds,
                        )
                        if on_answer_delta is not None
                        else None
                    ),
                )
            except _ChatGenerationTransportError as exc:
                last_error = exc
                if attempt == 0 and not answer_published:
                    continue
                raise
            if attempt == 0 and (status_code == 429 or status_code >= 500):
                continue
            if result is not None:
                elapsed_before_attempt_ms = max(
                    0,
                    round((attempt_started_at - started_at) * 1000),
                )
                result = replace(
                    result,
                    first_delta_ms=(
                        elapsed_before_attempt_ms + result.first_delta_ms
                        if result.first_delta_ms is not None
                        else None
                    ),
                    duration_ms=max(
                        0,
                        round((time.perf_counter() - started_at) * 1000),
                    ),
                    attempt_count=attempt + 1,
                )
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
        on_answer_delta: Callable[[str], None] | None = None,
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
                payload,
                on_answer_delta=on_answer_delta,
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
                    payload,
                    on_answer_delta=on_answer_delta,
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
            buffered = self.generate_json(
                messages=request_messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            if on_answer_delta is not None:
                extracted = IncrementalJSONTextField("answer").feed(
                    buffered.content
                )
                if extracted:
                    on_answer_delta(extracted)
            return buffered
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
    first_answer_timeout_seconds: float = 12,
) -> OpenAICompatibleChatGeneration:
    return OpenAICompatibleChatGeneration(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        timeout_seconds=timeout_seconds,
        first_answer_timeout_seconds=first_answer_timeout_seconds,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
    )
