from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx


class ChatGenerationError(ValueError):
    """A credential-safe model failure suitable for logs and operator UI."""


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
            raise ChatGenerationError("generation provider returned invalid structured output") from exc
        try:
            payload = json.loads(normalized[start : end + 1])
        except json.JSONDecodeError as nested:
            raise ChatGenerationError(
                "generation provider returned invalid structured output"
            ) from nested
    if not isinstance(payload, dict):
        raise ChatGenerationError("generation provider returned a non-object response")
    return payload


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
            raise ChatGenerationError("generation provider request timed out") from exc
        except httpx.HTTPError as exc:
            raise ChatGenerationError("generation provider request failed") from exc

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

    def generate_json(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> ChatGenerationResult:
        if not messages:
            raise ChatGenerationError("generation messages are required")
        payload: dict[str, Any] = {
            "model": self.identity.model_name,
            "messages": messages,
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": (
                self._max_output_tokens
                if max_output_tokens is None
                else max_output_tokens
            ),
            "response_format": {"type": "json_object"},
        }
        response = self._request_with_transient_retry(payload)
        # A few otherwise-compatible gateways do not implement response_format.
        # Retry only that validation class, never authentication or server failures.
        if response.status_code in {400, 404, 422}:
            payload.pop("response_format", None)
            response = self._request_with_transient_retry(payload)
        if response.status_code < 200 or response.status_code >= 300:
            raise ChatGenerationError(
                f"generation provider returned HTTP {response.status_code}"
            )
        try:
            body = response.json()
            choice = body["choices"][0]
            content_value = choice["message"]["content"]
            if isinstance(content_value, list):
                content = "".join(
                    str(block.get("text") or "")
                    for block in content_value
                    if isinstance(block, dict)
                )
            else:
                content = str(content_value)
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
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ChatGenerationError(
                "generation provider returned an invalid response"
            ) from exc
        return ChatGenerationResult(
            content=content,
            data=_json_object(content),
            finish_reason=finish_reason,
            usage=usage,
        )


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
