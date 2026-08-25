from __future__ import annotations

import base64
import hashlib
import io
import logging
import math
import os
import time
from collections.abc import Mapping
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from ..ports.image_intelligence import ImageIntelligenceProvider, VisionResult
from ..services.embedding import EmbeddingIdentity, validate_vectors


logger = logging.getLogger(__name__)
QWEN3_VL_DIMENSIONS = frozenset({256, 512, 768, 1024, 1536, 2048, 2560})
QWEN_IMAGE_PREPROCESSING_VERSION = "product-image-png-v2"
_RETRYABLE_STATUSES = {408, 409, 425, 429}
_MAX_SOURCE_PIXELS = 50_000_000
_MAX_EDGE = 1600
_PNG_COMPRESSION_LEVEL = 3


@lru_cache(maxsize=1)
def _shared_http_client() -> httpx.Client:
    """Reuse pooled DashScope connections across storefront requests."""

    return httpx.Client(
        limits=httpx.Limits(
            max_connections=50,
            max_keepalive_connections=20,
            keepalive_expiry=120.0,
        ),
    )


class ImageIntelligenceUnavailable(RuntimeError):
    """Raised when no reviewed image-intelligence provider is active."""


class ImageIntelligenceProviderError(ValueError):
    """Safe image provider failure without credentials or response bodies."""


class DeterministicImageFeatureAdapter:
    """Network-free contract adapter for lifecycle, RLS and ranking tests.

    It is deliberately not described as a production vision model. Production refuses
    this profile and must provide an approved provider through the same port.
    """

    identity = EmbeddingIdentity(provider="local", model_name="atc-image-feature", model_version="1", dimensions=384)

    def analyze(self, content: bytes, *, content_type: str) -> VisionResult:
        if not content:
            raise ValueError("image content is empty")
        vector = [0.0] * self.identity.dimensions
        for value in content:
            vector[value] += 1.0
        for index, offset in enumerate(range(0, len(content), max(1, len(content) // 128))):
            digest = hashlib.sha256(content[offset:offset + 64]).digest()
            vector[256 + (index % 128)] += (digest[0] + 1) / 256
        norm = math.sqrt(sum(value * value for value in vector))
        vector = [value / norm for value in vector] if norm else vector
        quality = min(1.0, 0.55 + math.log10(max(10, len(content))) / 10)
        return VisionResult(
            labels=[{"label": "product_image", "confidence": round(quality, 4)}, {"label": content_type, "confidence": 1.0}],
            risks=[{"type": "watermark", "status": "UNKNOWN", "requires_human_review": True}],
            quality_score=quality,
            embedding=vector,
        )


def normalize_dashscope_multimodal_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ImageIntelligenceProviderError(
            "图片 Embedding Base URL 必须是 HTTP(S) 地址"
        )
    if parsed.username is not None or parsed.password is not None:
        raise ImageIntelligenceProviderError(
            "图片 Embedding Base URL 不能包含账号或密码"
        )
    if parsed.query or parsed.fragment:
        raise ImageIntelligenceProviderError(
            "图片 Embedding Base URL 不能包含查询参数或页面片段"
        )
    path = parsed.path.rstrip("/")
    chat_suffix = "/chat/completions"
    if path.endswith(chat_suffix):
        path = path[: -len(chat_suffix)]
    compatible_suffix = "/compatible-mode/v1"
    if path.endswith(compatible_suffix):
        path = path[: -len(compatible_suffix)]
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def dashscope_multimodal_endpoint(base_url: str) -> str:
    normalized = normalize_dashscope_multimodal_base_url(base_url)
    suffix = "/services/embeddings/multimodal-embedding/multimodal-embedding"
    if normalized.endswith(suffix):
        return normalized
    if normalized.endswith("/api/v1"):
        return f"{normalized}{suffix}"
    return f"{normalized}/api/v1{suffix}"


def _normalized_image_data_uri(
    content: bytes,
    *,
    content_type: str,
) -> tuple[str, float]:
    if not content:
        raise ImageIntelligenceProviderError("图片内容为空")
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.width * source.height > _MAX_SOURCE_PIXELS:
                raise ImageIntelligenceProviderError("图片像素尺寸过大")
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.mode not in {"RGB", "L"}:
                background = Image.new("RGB", image.size, "white")
                if "A" in image.getbands():
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image.convert("RGB"))
                image = background
            else:
                image = image.convert("RGB")
            source_min_edge = min(image.size)
            image.thumbnail((_MAX_EDGE, _MAX_EDGE), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            # Level 9/``optimize=True`` saves little bandwidth for storefront
            # photos but can spend more than a second recompressing every query.
            # Level 3 keeps the exact same decoded pixels and strips metadata,
            # while making the synchronous preparation phase an order of
            # magnitude faster.
            image.save(
                output,
                format="PNG",
                optimize=False,
                compress_level=_PNG_COMPRESSION_LEVEL,
            )
    except ImageIntelligenceProviderError:
        raise
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise ImageIntelligenceProviderError(
            f"无法解析图片内容（{content_type or 'unknown'}）"
        ) from exc
    normalized = output.getvalue()
    if len(normalized) > 10 * 1024 * 1024:
        raise ImageIntelligenceProviderError("图片预处理后仍超过 10 MB")
    quality = max(0.5, min(1.0, source_min_edge / 768))
    encoded = base64.b64encode(normalized).decode("ascii")
    return f"data:image/png;base64,{encoded}", quality


class QwenVLImageEmbeddingAdapter:
    """DashScope HTTP adapter for Qwen3-VL independent image vectors."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        model_version: str,
        dimensions: int = 1024,
        timeout_seconds: float = 30,
        max_retry_count: int = 2,
        retry_base_seconds: float = 0.75,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise ImageIntelligenceProviderError("图片 Embedding API Key 不能为空")
        if not model_name.strip():
            raise ImageIntelligenceProviderError("图片 Embedding 模型名称不能为空")
        if dimensions not in QWEN3_VL_DIMENSIONS:
            raise ImageIntelligenceProviderError("Qwen3-VL 不支持该向量维度")
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise ImageIntelligenceProviderError("图片 Embedding 超时必须在 1–120 秒之间")
        if max_retry_count < 0 or max_retry_count > 5:
            raise ImageIntelligenceProviderError("图片 Embedding 重试次数必须在 0–5 之间")
        self._api_key = api_key.strip()
        self._endpoint = dashscope_multimodal_endpoint(base_url)
        self._timeout_seconds = float(timeout_seconds)
        self._max_retry_count = max_retry_count
        self._retry_base_seconds = max(0.0, retry_base_seconds)
        self._client = client or _shared_http_client()
        self.identity = EmbeddingIdentity(
            provider="dashscope",
            model_name=model_name.strip(),
            model_version=model_version.strip(),
            dimensions=dimensions,
        )

    def analyze(self, content: bytes, *, content_type: str) -> VisionResult:
        image_data, quality = _normalized_image_data_uri(
            content,
            content_type=content_type,
        )
        payload = {
            "model": self.identity.model_name,
            "input": {"contents": [{"image": image_data}]},
            "parameters": {
                "dimension": self.identity.dimensions,
                "output_type": "dense",
            },
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(self._max_retry_count + 1):
            try:
                response = self._client.post(
                    self._endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self._timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                if attempt < self._max_retry_count:
                    self._wait(attempt, "timeout")
                    continue
                raise ImageIntelligenceProviderError(
                    "图片 Embedding 请求超时"
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < self._max_retry_count:
                    self._wait(attempt, type(exc).__name__)
                    continue
                raise ImageIntelligenceProviderError(
                    "图片 Embedding 网络请求失败"
                ) from exc

            if not 200 <= response.status_code < 300:
                if (
                    attempt < self._max_retry_count
                    and (
                        response.status_code in _RETRYABLE_STATUSES
                        or 500 <= response.status_code <= 599
                    )
                ):
                    self._wait(attempt, f"HTTP {response.status_code}")
                    continue
                raise ImageIntelligenceProviderError(
                    f"图片 Embedding 服务返回 HTTP {response.status_code}"
                )
            try:
                body = response.json()
                output = body.get("output") if isinstance(body, Mapping) else None
                rows = output.get("embeddings") if isinstance(output, Mapping) else None
                first = rows[0] if isinstance(rows, list) and rows else None
                raw_vector = first.get("embedding") if isinstance(first, Mapping) else None
                vector = [float(value) for value in raw_vector]
                validate_vectors(
                    [vector],
                    expected_count=1,
                    dimensions=self.identity.dimensions,
                )
            except (TypeError, ValueError, KeyError) as exc:
                raise ImageIntelligenceProviderError(
                    "图片 Embedding 服务返回了无效向量"
                ) from exc
            return VisionResult(
                labels=[
                    {
                        "label": "product_image",
                        "confidence": round(quality, 4),
                    }
                ],
                risks=[],
                quality_score=quality,
                embedding=vector,
            )
        raise ImageIntelligenceProviderError("图片 Embedding 请求失败")

    def _wait(self, attempt: int, reason: str) -> None:
        delay = min(8.0, self._retry_base_seconds * (2**attempt))
        logger.warning(
            "image embedding retry %s/%s in %.2fs after %s",
            attempt + 1,
            self._max_retry_count,
            delay,
            reason,
        )
        if delay:
            time.sleep(delay)


def qwen_vl_image_embedding_provider(
    *,
    api_key: str,
    base_url: str,
    model_name: str,
    model_version: str,
    dimensions: int,
    timeout_seconds: float,
    max_retry_count: int,
) -> QwenVLImageEmbeddingAdapter:
    return QwenVLImageEmbeddingAdapter(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        model_version=model_version,
        dimensions=dimensions,
        timeout_seconds=timeout_seconds,
        max_retry_count=max_retry_count,
    )


def get_image_intelligence_provider() -> ImageIntelligenceProvider:
    profile = os.getenv("IMAGE_INTELLIGENCE_PROFILE", "deterministic").lower()
    app_env = os.getenv("APP_ENV", "development").lower()
    if profile == "deterministic":
        if app_env in {"production", "prod"}:
            raise ImageIntelligenceUnavailable(
                "deterministic image intelligence is forbidden in production"
            )
        return DeterministicImageFeatureAdapter()
    if profile == "disabled":
        raise ImageIntelligenceUnavailable("image intelligence is disabled")
    raise ImageIntelligenceUnavailable(
        f"image intelligence provider is not registered: {profile}"
    )
