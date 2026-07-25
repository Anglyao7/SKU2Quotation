from __future__ import annotations

import httpx
import pytest

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
