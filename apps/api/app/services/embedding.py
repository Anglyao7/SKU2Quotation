import hashlib
import logging
import math
import os
import re
import time
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol
from urllib.parse import urlsplit

import httpx


logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]", re.IGNORECASE)
DEFAULT_EMBEDDING_RETRY_COUNT = 3
MAX_EMBEDDING_RETRY_COUNT = 10
DEFAULT_EMBEDDING_RETRY_BASE_SECONDS = 1.0
MAX_EMBEDDING_RETRY_DELAY_SECONDS = 30.0
_RETRYABLE_EMBEDDING_HTTP_STATUSES = {408, 409, 425, 429}

# This deterministic vocabulary bridge is intentionally small. It makes local tests useful
# without pretending to be a production semantic model or making an external AI call.
PHRASE_ALIASES = {
    "water resistant": "waterproof",
    "water-resistant": "waterproof",
    "pet toy": "dog toy",
    "puppy": "dog",
    "canine": "dog",
    "non toxic": "nontoxic",
    "non-toxic": "nontoxic",
}


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    for phrase, canonical in PHRASE_ALIASES.items():
        normalized = normalized.replace(phrase, canonical)
    return " ".join(TOKEN_PATTERN.findall(normalized))


def tokenize(value: str) -> list[str]:
    return TOKEN_PATTERN.findall(normalize_text(value))


@dataclass(frozen=True)
class EmbeddingIdentity:
    provider: str
    model_name: str
    model_version: str
    dimensions: int
    distance_metric: str = "COSINE"


class EmbeddingProvider(Protocol):
    identity: EmbeddingIdentity

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingProviderError(ValueError):
    """A safe provider failure that never includes credentials or response bodies."""


class DeterministicFeatureHashEmbedding:
    """Network-free, repeatable development adapter behind a provider-neutral contract."""

    identity = EmbeddingIdentity(
        provider="local",
        model_name="atc-feature-hash",
        model_version="1",
        dimensions=384,
    )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        tokens = tokenize(text)
        features = [f"token:{token}" for token in tokens]
        features.extend(
            f"bigram:{left}_{right}" for left, right in zip(tokens, tokens[1:], strict=False)
        )
        vector = [0.0] * self.identity.dimensions
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.identity.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


class PrecomputedEmbedding:
    """Provider-compatible view over vectors fetched in bounded batches."""

    def __init__(
        self,
        *,
        identity: EmbeddingIdentity,
        vectors_by_text: Mapping[str, list[float]],
    ) -> None:
        self.identity = identity
        self._vectors_by_text = vectors_by_text

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return [self._vectors_by_text[text] for text in texts]
        except KeyError as exc:
            raise EmbeddingProviderError(
                "precomputed embedding is missing requested text"
            ) from exc


class OpenAICompatibleEmbedding:
    """Text embedding adapter for OpenAI-compatible ``/v1/embeddings`` APIs."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        dimensions: int,
        model_version: str,
        timeout_seconds: float = 20.0,
        max_retry_count: int = DEFAULT_EMBEDDING_RETRY_COUNT,
        retry_base_seconds: float = DEFAULT_EMBEDDING_RETRY_BASE_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise EmbeddingProviderError("TEXT_EMBEDDING_API_KEY is required")
        if not model_name.strip():
            raise EmbeddingProviderError("TEXT_EMBEDDING_MODEL is required")
        if dimensions < 1 or dimensions > 2000:
            raise EmbeddingProviderError(
                "TEXT_EMBEDDING_DIMENSIONS must be between 1 and 2000"
            )
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise EmbeddingProviderError(
                "TEXT_EMBEDDING_TIMEOUT_SECONDS must be between 0 and 120"
            )
        if max_retry_count < 0 or max_retry_count > MAX_EMBEDDING_RETRY_COUNT:
            raise EmbeddingProviderError(
                "TEXT_EMBEDDING_PROVIDER_RETRIES must be between 0 and 10"
            )
        if retry_base_seconds < 0 or retry_base_seconds > 30:
            raise EmbeddingProviderError(
                "TEXT_EMBEDDING_RETRY_BASE_SECONDS must be between 0 and 30"
            )
        self._api_key = api_key.strip()
        self._endpoint = _embedding_endpoint(base_url)
        self._timeout_seconds = timeout_seconds
        self.max_retry_count = max_retry_count
        self._retry_base_seconds = retry_base_seconds
        self._client = client or httpx.Client()
        self.identity = EmbeddingIdentity(
            provider="openai-compatible",
            model_name=model_name.strip(),
            model_version=model_version.strip() or f"1-d{dimensions}",
            dimensions=dimensions,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {
            "model": self.identity.model_name,
            "input": texts,
            "dimensions": self.identity.dimensions,
            "encoding_format": "float",
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(self.max_retry_count + 1):
            try:
                response = self._client.post(
                    self._endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self._timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                if attempt < self.max_retry_count:
                    self._wait_before_retry(attempt, reason="request timeout")
                    continue
                raise EmbeddingProviderError(
                    "embedding provider request timed out"
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < self.max_retry_count:
                    self._wait_before_retry(
                        attempt,
                        reason=f"network error ({type(exc).__name__})",
                    )
                    continue
                raise EmbeddingProviderError(
                    "embedding provider request failed"
                ) from exc

            if response.status_code < 200 or response.status_code >= 300:
                error = EmbeddingProviderError(
                    f"embedding provider returned HTTP {response.status_code}"
                )
                if (
                    attempt < self.max_retry_count
                    and _retryable_embedding_status(response.status_code)
                ):
                    self._wait_before_retry(
                        attempt,
                        reason=f"HTTP {response.status_code}",
                        response=response,
                    )
                    continue
                raise error

            try:
                body = response.json()
                rows = body["data"]
                ordered = sorted(rows, key=lambda item: int(item["index"]))
                vectors = [
                    [float(value) for value in item["embedding"]]
                    for item in ordered
                ]
                validate_vectors(
                    vectors,
                    expected_count=len(texts),
                    dimensions=self.identity.dimensions,
                )
            except (KeyError, TypeError, ValueError) as exc:
                if attempt < self.max_retry_count:
                    self._wait_before_retry(attempt, reason="invalid response")
                    continue
                raise EmbeddingProviderError(
                    "embedding provider returned an invalid response"
                ) from exc
            return vectors

        raise EmbeddingProviderError("embedding provider request failed")

    def _wait_before_retry(
        self,
        attempt: int,
        *,
        reason: str,
        response: httpx.Response | None = None,
    ) -> None:
        retry_number = attempt + 1
        delay = min(
            self._retry_base_seconds * (2**attempt),
            MAX_EMBEDDING_RETRY_DELAY_SECONDS,
        )
        if response is not None:
            retry_after = _retry_after_seconds(response)
            if retry_after is not None:
                delay = min(
                    max(delay, retry_after),
                    MAX_EMBEDDING_RETRY_DELAY_SECONDS,
                )
        logger.warning(
            "embedding provider retry %s/%s in %.2fs after %s",
            retry_number,
            self.max_retry_count,
            delay,
            reason,
        )
        if delay > 0:
            time.sleep(delay)


def _retryable_embedding_status(status_code: int) -> bool:
    return (
        status_code in _RETRYABLE_EMBEDDING_HTTP_STATUSES
        or 500 <= status_code <= 599
    )


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw_value = response.headers.get("Retry-After", "").strip()
    if not raw_value:
        return None
    try:
        value = float(raw_value)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def _embedding_endpoint(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EmbeddingProviderError("TEXT_EMBEDDING_BASE_URL must be an HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise EmbeddingProviderError(
            "TEXT_EMBEDDING_BASE_URL must not contain credentials"
        )
    if normalized.endswith("/v1/embeddings"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/embeddings"
    return f"{normalized}/v1/embeddings"


def configured_embedding_retry_count(
    values: Mapping[str, str] | None = None,
) -> int:
    if values is None:
        values = os.environ
    raw_value = values.get(
        "TEXT_EMBEDDING_PROVIDER_RETRIES",
        str(DEFAULT_EMBEDDING_RETRY_COUNT),
    ).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise EmbeddingProviderError(
            "TEXT_EMBEDDING_PROVIDER_RETRIES must be an integer"
        ) from exc
    if value < 0 or value > MAX_EMBEDDING_RETRY_COUNT:
        raise EmbeddingProviderError(
            "TEXT_EMBEDDING_PROVIDER_RETRIES must be between 0 and 10"
        )
    return value


def configured_embedding_retry_base_seconds(
    values: Mapping[str, str] | None = None,
) -> float:
    if values is None:
        values = os.environ
    raw_value = values.get(
        "TEXT_EMBEDDING_RETRY_BASE_SECONDS",
        str(DEFAULT_EMBEDDING_RETRY_BASE_SECONDS),
    ).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise EmbeddingProviderError(
            "TEXT_EMBEDDING_RETRY_BASE_SECONDS must be numeric"
        ) from exc
    if value < 0 or value > 30:
        raise EmbeddingProviderError(
            "TEXT_EMBEDDING_RETRY_BASE_SECONDS must be between 0 and 30"
        )
    return value


def configured_text_embedding_provider(
    values: Mapping[str, str] | None = None,
) -> EmbeddingProvider:
    """Build the configured provider; deterministic remains the safe default."""

    if values is None:
        values = os.environ
    profile = values.get("TEXT_EMBEDDING_PROFILE", "deterministic").strip().lower()
    if profile in {"deterministic", "local", "feature_hash"}:
        return DeterministicFeatureHashEmbedding()
    if profile not in {"openai", "openai_compatible", "openai-compatible"}:
        raise EmbeddingProviderError(
            f"unsupported TEXT_EMBEDDING_PROFILE: {profile}"
        )
    dimensions_text = values.get("TEXT_EMBEDDING_DIMENSIONS", "1024").strip()
    timeout_text = values.get("TEXT_EMBEDDING_TIMEOUT_SECONDS", "20").strip()
    try:
        dimensions = int(dimensions_text)
        timeout_seconds = float(timeout_text)
    except ValueError as exc:
        raise EmbeddingProviderError(
            "text embedding dimensions or timeout is invalid"
        ) from exc
    max_retry_count = configured_embedding_retry_count(values)
    retry_base_seconds = configured_embedding_retry_base_seconds(values)
    return openai_compatible_embedding_provider(
        api_key=values.get("TEXT_EMBEDDING_API_KEY", ""),
        base_url=values.get("TEXT_EMBEDDING_BASE_URL", ""),
        model_name=values.get("TEXT_EMBEDDING_MODEL", ""),
        dimensions=dimensions,
        model_version=values.get(
            "TEXT_EMBEDDING_MODEL_VERSION",
            f"1-d{dimensions}",
        ),
        timeout_seconds=timeout_seconds,
        max_retry_count=max_retry_count,
        retry_base_seconds=retry_base_seconds,
    )


@lru_cache(maxsize=8)
def _configured_openai_compatible_provider(
    api_key: str,
    base_url: str,
    model_name: str,
    dimensions: int,
    model_version: str,
    timeout_seconds: float,
    max_retry_count: int,
    retry_base_seconds: float,
) -> OpenAICompatibleEmbedding:
    return OpenAICompatibleEmbedding(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        dimensions=dimensions,
        model_version=model_version,
        timeout_seconds=timeout_seconds,
        max_retry_count=max_retry_count,
        retry_base_seconds=retry_base_seconds,
    )


def openai_compatible_embedding_provider(
    *,
    api_key: str,
    base_url: str,
    model_name: str,
    dimensions: int,
    model_version: str,
    timeout_seconds: float,
    max_retry_count: int = DEFAULT_EMBEDDING_RETRY_COUNT,
    retry_base_seconds: float = DEFAULT_EMBEDDING_RETRY_BASE_SECONDS,
) -> OpenAICompatibleEmbedding:
    """Reuse clients for identical credential and model configurations."""

    return _configured_openai_compatible_provider(
        api_key,
        base_url,
        model_name,
        dimensions,
        model_version,
        timeout_seconds,
        max_retry_count,
        retry_base_seconds,
    )


def precompute_embeddings(
    provider: EmbeddingProvider,
    texts: list[str],
    *,
    batch_size: int = 128,
) -> PrecomputedEmbedding:
    if batch_size < 1 or batch_size > 2048:
        raise EmbeddingProviderError("embedding batch size must be between 1 and 2048")
    unique_texts = list(dict.fromkeys(texts))
    vectors_by_text: dict[str, list[float]] = {}
    for start in range(0, len(unique_texts), batch_size):
        batch = unique_texts[start : start + batch_size]
        vectors = provider.embed(batch)
        validate_vectors(
            vectors,
            expected_count=len(batch),
            dimensions=provider.identity.dimensions,
        )
        vectors_by_text.update(zip(batch, vectors, strict=True))
    return PrecomputedEmbedding(
        identity=provider.identity,
        vectors_by_text=vectors_by_text,
    )


def validate_vectors(vectors: list[list[float]], *, expected_count: int, dimensions: int) -> None:
    if len(vectors) != expected_count:
        raise ValueError("embedding count does not match chunk count")
    for vector in vectors:
        if len(vector) != dimensions:
            raise ValueError("embedding dimension does not match provider contract")
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("embedding contains a non-finite value")


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimensions")
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / (left_norm * right_norm)))
