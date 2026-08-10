from __future__ import annotations

import httpx
import pytest

from app.services import embedding as embedding_service
from app.services.embedding import (
    DeterministicFeatureHashEmbedding,
    EmbeddingProviderError,
    OpenAICompatibleEmbedding,
    configured_text_embedding_provider,
)


def test_embedding_configuration_defaults_to_network_free_provider() -> None:
    provider = configured_text_embedding_provider({})

    assert isinstance(provider, DeterministicFeatureHashEmbedding)
    assert provider.identity.dimensions == 384


def test_embedding_configuration_builds_openai_compatible_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    configured_provider = object()

    def build_provider(
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        dimensions: int,
        model_version: str,
        timeout_seconds: float,
        max_retry_count: int,
        retry_base_seconds: float,
    ) -> object:
        captured.update(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            dimensions=dimensions,
            model_version=model_version,
            timeout_seconds=timeout_seconds,
            max_retry_count=max_retry_count,
            retry_base_seconds=retry_base_seconds,
        )
        return configured_provider

    monkeypatch.setattr(
        embedding_service,
        "openai_compatible_embedding_provider",
        build_provider,
    )
    provider = configured_text_embedding_provider(
        {
            "TEXT_EMBEDDING_PROFILE": "openai_compatible",
            "TEXT_EMBEDDING_API_KEY": "test-secret",
            "TEXT_EMBEDDING_BASE_URL": "https://embedding.example",
            "TEXT_EMBEDDING_MODEL": "text-embedding-3-large",
            "TEXT_EMBEDDING_MODEL_VERSION": "test-d1024",
            "TEXT_EMBEDDING_DIMENSIONS": "1024",
            "TEXT_EMBEDDING_TIMEOUT_SECONDS": "20",
            "TEXT_EMBEDDING_PROVIDER_RETRIES": "4",
            "TEXT_EMBEDDING_RETRY_BASE_SECONDS": "1.5",
        }
    )

    assert provider is configured_provider
    assert captured == {
        "api_key": "test-secret",
        "base_url": "https://embedding.example",
        "model_name": "text-embedding-3-large",
        "dimensions": 1024,
        "model_version": "test-d1024",
        "timeout_seconds": 20.0,
        "max_retry_count": 4,
        "retry_base_seconds": 1.5,
    }


def test_openai_compatible_embedding_uses_embeddings_endpoint_and_dimensions() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleEmbedding(
            api_key="test-secret",
            base_url="https://embedding.example/v1",
            model_name="text-embedding-3-large",
            model_version="test-d2",
            dimensions=2,
            client=client,
        )
        vectors = provider.embed(["first", "second"])

    assert captured["url"] == "https://embedding.example/v1/embeddings"
    assert captured["authorization"] == "Bearer test-secret"
    assert '"dimensions":2' in str(captured["body"]).replace(" ", "")
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


def test_openai_compatible_embedding_returns_safe_http_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "do not expose this"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleEmbedding(
            api_key="test-secret",
            base_url="https://embedding.example",
            model_name="text-embedding-3-large",
            model_version="test-d2",
            dimensions=2,
            client=client,
        )
        with pytest.raises(
            EmbeddingProviderError,
            match="embedding provider returned HTTP 404",
        ):
            provider.embed(["query"])


def test_openai_compatible_embedding_retries_transient_http_errors() -> None:
    statuses = iter((503, 429, 200))
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        status = next(statuses)
        if status != 200:
            return httpx.Response(status, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleEmbedding(
            api_key="test-secret",
            base_url="https://embedding.example",
            model_name="text-embedding-3-large",
            model_version="test-d2",
            dimensions=2,
            max_retry_count=2,
            retry_base_seconds=0,
            client=client,
        )
        vectors = provider.embed(["query"])

    assert attempts == 3
    assert vectors == [[1.0, 0.0]]


def test_openai_compatible_embedding_retries_timeout() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("temporary timeout", request=request)
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleEmbedding(
            api_key="test-secret",
            base_url="https://embedding.example",
            model_name="text-embedding-3-large",
            model_version="test-d2",
            dimensions=2,
            max_retry_count=1,
            retry_base_seconds=0,
            client=client,
        )
        vectors = provider.embed(["query"])

    assert attempts == 2
    assert vectors == [[1.0, 0.0]]


def test_openai_compatible_embedding_does_not_retry_authentication_error() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleEmbedding(
            api_key="test-secret",
            base_url="https://embedding.example",
            model_name="text-embedding-3-large",
            model_version="test-d2",
            dimensions=2,
            max_retry_count=3,
            retry_base_seconds=0,
            client=client,
        )
        with pytest.raises(
            EmbeddingProviderError,
            match="embedding provider returned HTTP 401",
        ):
            provider.embed(["query"])

    assert attempts == 1
