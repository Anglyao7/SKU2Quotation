"""Alibaba Cloud Model Studio Batch File adapter for catalog translation."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx

from ..translation_constants import MAX_TRANSLATION_TIMEOUT_SECONDS

from .catalog_translation import (
    catalog_translation_values_payload,
    parse_catalog_translation_values,
    validate_catalog_translation_values,
)
from .translation import (
    OpenAICompatibleTranslator,
    TranslationIdentity,
    TranslationProviderError,
    _openai_chat_completions_endpoint,
    _safe_upstream_text,
)


DEFAULT_QWEN_BATCH_BASE_URL = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
DEFAULT_QWEN_BATCH_MODEL = "qwen3.7-flash-2026-07-15"
QWEN_BATCH_PROMPT_VERSION = "catalog-text-v1"
QWEN_BATCH_COMPLETION_WINDOW = "24h"
# Keep each JSONL row small enough that one language can expose hundreds of
# independent provider requests in a single Batch file.  The provider accepts
# up to 50,000 rows per file; compact rows improve parallelism and also reduce
# the blast radius of one malformed structured response.
QWEN_BATCH_REQUEST_MAX_ITEMS = 20
QWEN_BATCH_REQUEST_MAX_CHARACTERS = 3_000
QWEN_BATCH_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "expired",
    "cancelled",
}
_QWEN_BATCH_TRANSPORT_MAX_ATTEMPTS = 3
_QWEN_BATCH_RETRYABLE_STATUS_CODES = {
    408,
    425,
    429,
    500,
    502,
    503,
    504,
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QwenBatchConfiguration:
    base_url: str
    api_key: str = field(repr=False)
    model_name: str = DEFAULT_QWEN_BATCH_MODEL
    timeout_seconds: int = 20
    max_tokens: int = 16_384

    @property
    def identity(self) -> TranslationIdentity:
        host = urlsplit(self.base_url).netloc.casefold()
        fingerprint = hashlib.sha256(
            (
                f"{host}\0{self.model_name}\0{QWEN_BATCH_PROMPT_VERSION}"
                "\0thinking:false"
            ).encode("utf-8")
        ).hexdigest()[:12]
        return TranslationIdentity(
            provider="qwen-batch",
            version=f"{QWEN_BATCH_PROMPT_VERSION}:{self.model_name}:{fingerprint}"[
                :120
            ],
        )


@dataclass(frozen=True, slots=True)
class QwenBatchStatus:
    id: str
    status: str
    input_file_id: str | None
    output_file_id: str | None
    error_file_id: str | None
    total_requests: int
    completed_requests: int
    failed_requests: int
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class QwenBatchItemFailure:
    """One provider item that could not be safely imported."""

    custom_id: str
    request: dict[str, Any]
    error_message: str

    @property
    def value_count(self) -> int:
        values = self.request.get("values")
        return len(values) if isinstance(values, list) else 0


@dataclass(frozen=True, slots=True)
class QwenBatchParseResult:
    """Validated output plus the exact request subsets that need retrying."""

    translations_by_locale: dict[str, dict[str, str]]
    successful_request_ids: tuple[str, ...]
    failures: tuple[QwenBatchItemFailure, ...]

    @property
    def processed_values(self) -> int:
        return sum(len(values) for values in self.translations_by_locale.values())

    @property
    def failed_values(self) -> int:
        return sum(failure.value_count for failure in self.failures)


def qwen_batch_api_base_url(value: str, *, production: bool) -> str:
    """Normalize any accepted compatible URL to its `/v1` API root."""

    chat_endpoint = _openai_chat_completions_endpoint(
        value,
        production=production,
    )
    parsed = urlsplit(chat_endpoint)
    suffix = "/chat/completions"
    path = parsed.path
    if not path.endswith(suffix):  # pragma: no cover - guarded by normalizer
        raise TranslationProviderError(
            "Qwen Batch base URL could not be normalized"
        )
    return urlunsplit((parsed.scheme, parsed.netloc, path[: -len(suffix)], "", ""))


def qwen_batch_translation_requests(
    values_by_source_locale: Mapping[str, list[str]],
    *,
    job_id: UUID,
    max_items: int = QWEN_BATCH_REQUEST_MAX_ITEMS,
    max_characters: int = QWEN_BATCH_REQUEST_MAX_CHARACTERS,
    generation: int = 0,
    sequence_start: int = 0,
) -> list[dict[str, Any]]:
    """Split a de-duplicated text corpus into deterministic Batch requests."""

    if (
        max_items < 1
        or max_items > 999
        or max_characters < 1
        or generation < 0
        or sequence_start < 0
    ):
        raise ValueError("invalid Qwen Batch translation request limits")
    requests: list[dict[str, Any]] = []
    sequence = sequence_start
    for source_locale in sorted(values_by_source_locale):
        values = list(
            dict.fromkeys(
                value.strip()
                for value in values_by_source_locale[source_locale]
                if value and value.strip()
            )
        )
        current: list[str] = []
        current_characters = 0

        def flush() -> None:
            nonlocal current, current_characters, sequence
            if not current:
                return
            digest = hashlib.sha256(
                "\0".join(current).encode("utf-8")
            ).hexdigest()[:12]
            requests.append(
                {
                    "custom_id": (
                        f"atc-{job_id.hex[:10]}-r{generation:02d}-"
                        f"{sequence:05d}-{digest}"
                    ),
                    "source_locale": source_locale,
                    "values": current,
                }
            )
            sequence += 1
            current = []
            current_characters = 0

        for value in values:
            if current and (
                len(current) >= max_items
                or current_characters + len(value) > max_characters
            ):
                flush()
            current.append(value)
            current_characters += len(value)
        flush()
    return requests


class QwenBatchClient:
    """Small HTTP adapter around DashScope's OpenAI-compatible Batch API."""

    translates_mixed_language_text = True

    def __init__(
        self,
        configuration: QwenBatchConfiguration,
        *,
        production: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        if not configuration.api_key.strip():
            raise TranslationProviderError("Qwen Batch API key is required")
        if not configuration.model_name.strip():
            raise TranslationProviderError("Qwen Batch model is required")
        if (
            configuration.timeout_seconds < 1
            or configuration.timeout_seconds > MAX_TRANSLATION_TIMEOUT_SECONDS
        ):
            raise TranslationProviderError(
                "Qwen Batch timeout must be between 1 and "
                f"{MAX_TRANSLATION_TIMEOUT_SECONDS} seconds"
            )
        self.configuration = configuration
        self._base_url = qwen_batch_api_base_url(
            configuration.base_url,
            production=production,
        )
        self._headers = {
            "Authorization": f"Bearer {configuration.api_key.strip()}",
        }
        self._client = client or httpx.Client(trust_env=False)
        self._prompt_adapter = OpenAICompatibleTranslator(
            base_url=self._base_url,
            api_key=configuration.api_key,
            model=configuration.model_name,
            timeout_seconds=float(configuration.timeout_seconds),
            max_tokens=configuration.max_tokens,
            reasoning_effort="",
            enable_thinking=False,
            production=production,
            client=self._client,
        )

    @property
    def identity(self) -> TranslationIdentity:
        """Keep Batch and real-time tail calls in one translation memory."""

        return self.configuration.identity

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str:
        """Translate one request through Qwen's real-time compatible API."""

        return self._prompt_adapter.translate(
            text,
            source_locale=source_locale,
            target_locale=target_locale,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        retry_mode: Literal["none", "safe", "upload"] = "none",
        **kwargs: Any,
    ) -> httpx.Response:
        max_attempts = (
            _QWEN_BATCH_TRANSPORT_MAX_ATTEMPTS
            if retry_mode != "none"
            else 1
        )
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=self._headers,
                    timeout=float(self.configuration.timeout_seconds),
                    **kwargs,
                )
            except httpx.TimeoutException as exc:
                if self._retryable_transport_error(
                    exc,
                    retry_mode=retry_mode,
                    attempt=attempt,
                    max_attempts=max_attempts,
                ):
                    self._wait_before_transport_retry(
                        method=method,
                        path=path,
                        attempt=attempt,
                        reason=type(exc).__name__,
                    )
                    continue
                raise TranslationProviderError(
                    "上游 Qwen Batch 请求超时"
                    f"（等待 {self.configuration.timeout_seconds} 秒，"
                    f"{method} {path}）",
                    category="UPSTREAM_TIMEOUT",
                    retryable=True,
                ) from exc
            except httpx.HTTPError as exc:
                if self._retryable_transport_error(
                    exc,
                    retry_mode=retry_mode,
                    attempt=attempt,
                    max_attempts=max_attempts,
                ):
                    self._wait_before_transport_retry(
                        method=method,
                        path=path,
                        attempt=attempt,
                        reason=type(exc).__name__,
                    )
                    continue
                raise TranslationProviderError(
                    "无法连接上游 Qwen Batch 服务"
                    f"（{type(exc).__name__}，{method} {path}）",
                    category="UPSTREAM_NETWORK",
                    retryable=True,
                ) from exc
            if response.status_code < 200 or response.status_code >= 300:
                if (
                    retry_mode == "safe"
                    and attempt < max_attempts
                    and response.status_code
                    in _QWEN_BATCH_RETRYABLE_STATUS_CODES
                ):
                    self._wait_before_transport_retry(
                        method=method,
                        path=path,
                        attempt=attempt,
                        reason=f"HTTP {response.status_code}",
                    )
                    continue
                message = self._response_error_message(response)
                suffix = f": {message}" if message else ""
                raise TranslationProviderError(
                    f"上游 Qwen Batch 返回 HTTP "
                    f"{response.status_code}{suffix}",
                    category="UPSTREAM_HTTP",
                    retryable=(
                        response.status_code
                        in _QWEN_BATCH_RETRYABLE_STATUS_CODES
                    ),
                    upstream_status_code=response.status_code,
                )
            return response
        raise AssertionError("Qwen Batch transport retry loop did not return")

    @staticmethod
    def _retryable_transport_error(
        exc: httpx.HTTPError,
        *,
        retry_mode: Literal["none", "safe", "upload"],
        attempt: int,
        max_attempts: int,
    ) -> bool:
        if retry_mode == "none" or attempt >= max_attempts:
            return False
        if retry_mode == "safe":
            return isinstance(exc, httpx.TransportError)
        # Retrying an upload is safe only while the connection or request
        # write failed. A read failure is ambiguous because the provider may
        # already have stored the file and only lost the response.
        return isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.WriteError,
                httpx.WriteTimeout,
            ),
        )

    @staticmethod
    def _wait_before_transport_retry(
        *,
        method: str,
        path: str,
        attempt: int,
        reason: str,
    ) -> None:
        delay = min(2 ** (attempt - 1), 4)
        logger.warning(
            "Qwen Batch transport retry %s/%s in %ss after %s for %s %s",
            attempt,
            _QWEN_BATCH_TRANSPORT_MAX_ATTEMPTS - 1,
            delay,
            reason,
            method,
            path,
        )
        time.sleep(delay)

    @staticmethod
    def _response_error_message(response: httpx.Response) -> str | None:
        try:
            body = response.json()
        except (TypeError, ValueError):
            return None
        if not isinstance(body, Mapping):
            return None
        error = body.get("error")
        source = error if isinstance(error, Mapping) else body
        raw_code = source.get("code") or source.get("type")
        raw_message = source.get("message") or source.get("detail")
        code = raw_code if isinstance(raw_code, str) else None
        message = raw_message if isinstance(raw_message, str) else None
        combined = (
            f"{code}: {message}"
            if code and message and code.casefold() != message.casefold()
            else message or code
        )
        if not combined:
            return None
        # Upstream messages are useful for operators but may echo payloads.
        # Keep a short, single-line diagnostic and never include request URLs
        # or the Authorization header.
        return _safe_upstream_text(combined)

    def jsonl_content(
        self,
        requests: list[dict[str, Any]],
        *,
        target_locale: str,
    ) -> bytes:
        lines: list[str] = []
        for request in requests:
            values = request.get("values")
            source_locale = request.get("source_locale")
            custom_id = request.get("custom_id")
            if (
                not isinstance(values, list)
                or not values
                or not all(isinstance(value, str) for value in values)
                or not isinstance(source_locale, str)
                or not isinstance(custom_id, str)
            ):
                raise TranslationProviderError(
                    "Qwen Batch translation snapshot is invalid"
                )
            source_text, _protected = catalog_translation_values_payload(values)
            body = self._prompt_adapter.request_payload(
                source_text,
                source_locale=source_locale,
                target_locale=target_locale,
                enable_thinking=False,
            )
            lines.append(
                json.dumps(
                    {
                        "custom_id": custom_id,
                        "method": "POST",
                        "url": "/v1/chat/completions",
                        "body": body,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        return ("\n".join(lines) + "\n").encode("utf-8")

    def upload_jsonl(self, content: bytes, *, filename: str) -> str:
        response = self._request(
            "POST",
            "/files",
            retry_mode="upload",
            data={"purpose": "batch"},
            files={"file": (filename, content, "application/jsonl")},
        )
        try:
            file_id = response.json()["id"]
        except (KeyError, TypeError, ValueError) as exc:
            raise TranslationProviderError(
                "Qwen Batch file upload returned an invalid response"
            ) from exc
        if not isinstance(file_id, str) or not file_id.strip():
            raise TranslationProviderError(
                "Qwen Batch file upload returned an invalid response"
            )
        return file_id.strip()

    def create_batch(
        self,
        input_file_id: str,
        *,
        name: str,
        description: str,
    ) -> QwenBatchStatus:
        response = self._request(
            "POST",
            "/batches",
            json={
                "input_file_id": input_file_id,
                "endpoint": "/v1/chat/completions",
                "completion_window": QWEN_BATCH_COMPLETION_WINDOW,
                "metadata": {
                    "ds_name": name[:100],
                    "ds_description": description[:200],
                },
            },
        )
        return self._batch_status(response.json())

    def retrieve_batch(self, batch_id: str) -> QwenBatchStatus:
        response = self._request(
            "GET",
            f"/batches/{batch_id}",
            retry_mode="safe",
        )
        return self._batch_status(response.json())

    def cancel_batch(self, batch_id: str) -> QwenBatchStatus:
        """Cancel provider work that has not completed yet."""

        response = self._request("POST", f"/batches/{batch_id}/cancel")
        return self._batch_status(response.json())

    def find_batch(self, input_file_id: str) -> QwenBatchStatus | None:
        """Recover a task created just before a process interruption."""

        response = self._request(
            "GET",
            "/batches",
            retry_mode="safe",
            params={"input_file_ids": input_file_id, "limit": 100},
        )
        try:
            body = response.json()
        except (TypeError, ValueError) as exc:
            raise TranslationProviderError(
                "Qwen Batch task list returned an invalid response"
            ) from exc
        if not isinstance(body, Mapping) or "data" not in body:
            raise TranslationProviderError(
                "Qwen Batch task list returned an invalid response"
            )
        rows = body["data"]
        # DashScope returns ``data: null`` (rather than an empty array) when
        # the filter has no matching Batch.  That is a valid empty result and
        # means the caller may safely create the task for this uploaded file.
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise TranslationProviderError(
                "Qwen Batch task list returned an invalid response"
            )
        matches: list[QwenBatchStatus] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            status = self._batch_status(row)
            if status.input_file_id == input_file_id:
                matches.append(status)
        return matches[0] if matches else None

    def download_file(self, file_id: str) -> bytes:
        return self._request(
            "GET",
            f"/files/{file_id}/content",
            retry_mode="safe",
        ).content

    def delete_file(self, file_id: str) -> bool:
        response = self._request(
            "DELETE",
            f"/files/{file_id}",
            retry_mode="safe",
        )
        try:
            return bool(response.json().get("deleted"))
        except (AttributeError, TypeError, ValueError):
            return False

    @staticmethod
    def _batch_status(body: object) -> QwenBatchStatus:
        if not isinstance(body, Mapping):
            raise TranslationProviderError(
                "Qwen Batch returned an invalid task response"
            )
        batch_id = body.get("id")
        status = body.get("status")
        if not isinstance(batch_id, str) or not isinstance(status, str):
            raise TranslationProviderError(
                "Qwen Batch returned an invalid task response"
            )
        counts = body.get("request_counts")
        counts = counts if isinstance(counts, Mapping) else {}
        errors = body.get("errors")
        error_message: str | None = None
        if isinstance(errors, Mapping):
            raw_message = errors.get("message") or errors.get("code")
            if isinstance(raw_message, str):
                error_message = " ".join(raw_message.split())[:300] or None

        def optional_string(key: str) -> str | None:
            value = body.get(key)
            return value.strip() if isinstance(value, str) and value.strip() else None

        def count(key: str) -> int:
            value = counts.get(key, 0)
            return max(0, int(value)) if isinstance(value, (int, float)) else 0

        return QwenBatchStatus(
            id=batch_id,
            status=status.strip().lower(),
            input_file_id=optional_string("input_file_id"),
            output_file_id=optional_string("output_file_id"),
            error_file_id=optional_string("error_file_id"),
            total_requests=count("total"),
            completed_requests=count("completed"),
            failed_requests=count("failed"),
            error_message=error_message,
        )

    def parse_output(
        self,
        content: bytes,
        requests: list[dict[str, Any]],
        *,
        target_locale: str,
    ) -> QwenBatchParseResult:
        expected = {
            str(request["custom_id"]): request for request in requests
        }
        if len(expected) != len(requests):
            raise TranslationProviderError(
                "Qwen Batch translation snapshot contains duplicate custom_id values"
            )
        seen: set[str] = set()
        successful: list[str] = []
        failures: list[QwenBatchItemFailure] = []
        translations_by_locale: dict[str, dict[str, str]] = {}

        def item_error(row: Mapping[str, Any], fallback: str) -> str:
            error = row.get("error")
            if isinstance(error, Mapping):
                raw = error.get("message") or error.get("code")
                if isinstance(raw, str) and raw.strip():
                    return " ".join(raw.split())[:300]
            return fallback

        def fail(
            custom_id: str,
            request: dict[str, Any],
            message: str,
        ) -> None:
            failures.append(
                QwenBatchItemFailure(
                    custom_id=custom_id,
                    request=dict(request),
                    error_message=" ".join(message.split())[:300],
                )
            )

        try:
            lines = content.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise TranslationProviderError(
                "Qwen Batch result file is not valid UTF-8"
            ) from exc
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TranslationProviderError(
                    "Qwen Batch result file contains invalid JSONL"
                ) from exc
            if not isinstance(row, Mapping):
                raise TranslationProviderError(
                    "Qwen Batch result file contains an invalid row"
                )
            custom_id = row.get("custom_id")
            if not isinstance(custom_id, str) or custom_id not in expected:
                raise TranslationProviderError(
                    "Qwen Batch result contains an unknown custom_id"
                )
            if custom_id in seen:
                raise TranslationProviderError(
                    "Qwen Batch result contains a duplicate custom_id"
                )
            seen.add(custom_id)
            request = expected[custom_id]
            response = row.get("response")
            if not isinstance(response, Mapping):
                fail(
                    custom_id,
                    request,
                    item_error(row, "Qwen Batch result is missing a response"),
                )
                continue
            status_code = response.get("status_code")
            if not isinstance(status_code, int) or not 200 <= status_code < 300:
                fail(
                    custom_id,
                    request,
                    item_error(
                        row,
                        f"Qwen Batch item returned HTTP {status_code or 'unknown'}",
                    ),
                )
                continue
            response_body = response.get("body")
            if not isinstance(response_body, Mapping):
                fail(
                    custom_id,
                    request,
                    "Qwen Batch item returned an invalid response body",
                )
                continue
            values = request["values"]
            source_locale = str(request["source_locale"])
            try:
                source_text, protected = catalog_translation_values_payload(values)
                translated_text = self._prompt_adapter.translated_response(
                    response_body,
                    source_text=source_text,
                )
                translated_values = parse_catalog_translation_values(
                    values,
                    translated_text,
                    protected=protected,
                )
                translated_values = validate_catalog_translation_values(
                    values,
                    translated_values,
                    translator=None,
                    source_locale=source_locale,
                    target_locale=target_locale,
                )
            except (
                TranslationProviderError,
                ValueError,
                TypeError,
                KeyError,
                IndexError,
            ) as exc:
                fail(
                    custom_id,
                    request,
                    str(exc) or "Qwen Batch item returned invalid structured content",
                )
                continue
            translations_by_locale.setdefault(source_locale, {}).update(
                zip(values, translated_values, strict=True)
            )
            successful.append(custom_id)
        for custom_id in sorted(set(expected) - seen):
            fail(
                custom_id,
                expected[custom_id],
                "Qwen Batch result is missing this request",
            )
        return QwenBatchParseResult(
            translations_by_locale=translations_by_locale,
            successful_request_ids=tuple(successful),
            failures=tuple(failures),
        )
