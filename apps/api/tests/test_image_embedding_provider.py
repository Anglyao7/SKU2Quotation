from __future__ import annotations

import base64
import io
import json

import httpx
import pytest
from PIL import Image

from app.adapters import image_intelligence as image_adapter
from app.adapters.image_intelligence import (
    ImageIntelligenceProviderError,
    QwenVLImageEmbeddingAdapter,
    dashscope_multimodal_endpoint,
)
from app.services.image_embedding_configuration import managed_image_model_version


def _png_bytes(*, size: tuple[int, int] = (8, 6)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", size, (20, 160, 120, 180)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("base_url", "expected"),
    (
        (
            "https://dashscope.aliyuncs.com",
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
            "multimodal-embedding/multimodal-embedding",
        ),
        (
            "https://dashscope.aliyuncs.com/api/v1/",
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
            "multimodal-embedding/multimodal-embedding",
        ),
        (
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
            "multimodal-embedding/multimodal-embedding",
        ),
        (
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
            "multimodal-embedding/multimodal-embedding",
        ),
        (
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
            "multimodal-embedding/multimodal-embedding",
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
            "multimodal-embedding/multimodal-embedding",
        ),
    ),
)
def test_dashscope_multimodal_endpoint_normalization(
    base_url: str,
    expected: str,
) -> None:
    assert dashscope_multimodal_endpoint(base_url) == expected


def test_dashscope_multimodal_endpoint_rejects_console_page_url() -> None:
    with pytest.raises(
        ImageIntelligenceProviderError,
        match="不能包含查询参数或页面片段",
    ):
        dashscope_multimodal_endpoint(
            "https://bailian.console.aliyun.com/cn-beijing?tab=model"
            "#/model-market/detail/qwen3-vl-embedding"
        )


def test_qwen_image_embedding_sends_independent_base64_image_vector() -> None:
    captured: dict[str, object] = {}
    vector = [0.0] * 255 + [1.0]

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "output": {
                    "embeddings": [
                        {"index": 0, "type": "image", "embedding": vector}
                    ]
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = QwenVLImageEmbeddingAdapter(
            api_key="test-secret",
            base_url="https://dashscope.aliyuncs.com",
            model_name="qwen3-vl-embedding",
            model_version="test-d256",
            dimensions=256,
            client=client,
        )
        result = provider.analyze(_png_bytes(), content_type="image/png")

    body = captured["body"]
    assert isinstance(body, dict)
    assert captured["authorization"] == "Bearer test-secret"
    assert str(captured["url"]).endswith(
        "/services/embeddings/multimodal-embedding/multimodal-embedding"
    )
    assert body["model"] == "qwen3-vl-embedding"
    assert body["parameters"] == {"dimension": 256, "output_type": "dense"}
    image_data = body["input"]["contents"][0]["image"]
    assert image_data.startswith("data:image/png;base64,")
    assert result.embedding == vector
    assert 0.5 <= result.quality_score <= 1.0


def test_qwen_image_embedding_uses_fast_png_compression_without_changing_pixels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_image = ""
    vector = [0.0] * 255 + [1.0]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_image
        body = json.loads(request.content)
        captured_image = body["input"]["contents"][0]["image"]
        return httpx.Response(
            200,
            json={"output": {"embeddings": [{"embedding": vector}]}},
        )

    monkeypatch.setattr(image_adapter, "_PNG_COMPRESSION_LEVEL", 3)
    source = _png_bytes(size=(64, 48))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = QwenVLImageEmbeddingAdapter(
            api_key="test-secret",
            base_url="https://dashscope.aliyuncs.com",
            model_name="qwen3-vl-embedding",
            model_version="test-d256",
            dimensions=256,
            client=client,
        )
        provider.analyze(source, content_type="image/png")

    encoded = captured_image.removeprefix("data:image/png;base64,")
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as normalized:
        normalized.load()
        assert normalized.size == (64, 48)
        assert normalized.convert("RGBA").getpixel((0, 0)) == (89, 188, 160, 255)


def test_qwen_image_embedding_retries_transient_status() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"message": "must not leak"})
        return httpx.Response(
            200,
            json={
                "output": {
                    "embeddings": [{"embedding": [1.0] + [0.0] * 255}]
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = QwenVLImageEmbeddingAdapter(
            api_key="test-secret",
            base_url="https://dashscope.aliyuncs.com",
            model_name="qwen3-vl-embedding",
            model_version="test-d256",
            dimensions=256,
            max_retry_count=1,
            retry_base_seconds=0,
            client=client,
        )
        result = provider.analyze(_png_bytes(), content_type="image/png")

    assert attempts == 2
    assert len(result.embedding) == 256


def test_qwen_image_embedding_rejects_oversized_pixel_canvas_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(500)

    monkeypatch.setattr(image_adapter, "_MAX_SOURCE_PIXELS", 1)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = QwenVLImageEmbeddingAdapter(
            api_key="test-secret",
            base_url="https://dashscope.aliyuncs.com",
            model_name="qwen3-vl-embedding",
            model_version="test-d256",
            dimensions=256,
            client=client,
        )
        with pytest.raises(ImageIntelligenceProviderError, match="像素尺寸过大"):
            provider.analyze(_png_bytes(), content_type="image/png")

    assert requested is False


def test_managed_image_model_version_captures_preprocessing_identity() -> None:
    first = managed_image_model_version(
        base_url="https://dashscope.aliyuncs.com",
        model_name="qwen3-vl-embedding",
        dimensions=1024,
    )
    repeated = managed_image_model_version(
        base_url="https://dashscope.aliyuncs.com/",
        model_name="qwen3-vl-embedding",
        dimensions=1024,
    )
    compatible_mode = managed_image_model_version(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3-vl-embedding",
        dimensions=1024,
    )
    changed = managed_image_model_version(
        base_url="https://dashscope.aliyuncs.com",
        model_name="qwen3-vl-embedding",
        dimensions=768,
    )

    assert first == repeated
    assert first == compatible_mode
    assert first != changed
    assert "product-image-png-v2" in first
