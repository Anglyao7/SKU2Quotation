from __future__ import annotations

import json

import httpx
import pytest

from app.services import embedding as embedding_service
from app.services.embedding import (
    DeterministicFeatureHashEmbedding,
    EmbeddingProviderError,
    OpenAICompatibleEmbedding,
    configured_text_embedding_provider,
    precompute_embeddings,
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


def test_precompute_embeddings_bisects_rejected_aggregate_batches() -> None:
    request_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.read())["input"]
        request_sizes.append(len(inputs))
        if len(inputs) > 1:
            return httpx.Response(400)
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]},
        )

    texts = ["first", "second", "third", "fourth"]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleEmbedding(
            api_key="test-secret",
            base_url="https://embedding.example",
            model_name="text-embedding-3-large",
            model_version="test-d2",
            dimensions=2,
            max_retry_count=0,
            client=client,
        )
        prepared = precompute_embeddings(provider, texts, batch_size=4)

    assert prepared.embed(texts) == [[1.0, 0.0]] * 4
    assert request_sizes == [4, 2, 1, 1, 2, 1, 1]


def test_precompute_embeddings_bounds_batches_by_aggregate_token_budget() -> None:
    request_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.read())["input"]
        request_sizes.append(len(inputs))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [1.0, 0.0]}
                    for index, _value in enumerate(inputs)
                ]
            },
        )

    texts = ["一二三四", "五六七八", "九十十一"]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleEmbedding(
            api_key="test-secret",
            base_url="https://embedding.example",
            model_name="text-embedding-3-large",
            model_version="test-d2",
            dimensions=2,
            max_retry_count=0,
            client=client,
        )
        prepared = precompute_embeddings(
            provider,
            texts,
            batch_size=10,
            max_batch_tokens=8,
        )

    assert prepared.embed(texts) == [[1.0, 0.0]] * 3
    assert request_sizes == [2, 1]


def test_precompute_embeddings_identifies_bad_singleton_without_exposing_text() -> None:
    private_text = "customer-private-invalid-input"

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.read())["input"]
        if private_text in inputs:
            return httpx.Response(400)
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
            max_retry_count=0,
            client=client,
        )
        with pytest.raises(EmbeddingProviderError) as raised:
            precompute_embeddings(
                provider,
                ["valid input", private_text],
                batch_size=2,
            )

    message = str(raised.value)
    assert "embedding input rejected with HTTP 400" in message
    assert "fingerprint=" in message
    assert "estimated_tokens=" in message
    assert private_text not in message


def test_precompute_embeddings_rejects_oversized_text_before_network_call() -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleEmbedding(
            api_key="test-secret",
            base_url="https://embedding.example",
            model_name="text-embedding-3-large",
            model_version="test-d2",
            dimensions=2,
            max_retry_count=0,
            client=client,
        )
        with pytest.raises(
            EmbeddingProviderError,
            match="embedding input exceeds safe token budget",
        ):
            precompute_embeddings(
                provider,
                ["超长文本" * 20],
                max_input_tokens=10,
            )

    assert requests == 0
