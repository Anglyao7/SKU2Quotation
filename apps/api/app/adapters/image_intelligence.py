from __future__ import annotations

import hashlib
import math
import os

from ..ports.image_intelligence import ImageIntelligenceProvider, VisionResult
from ..services.embedding import EmbeddingIdentity


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


def get_image_intelligence_provider() -> ImageIntelligenceProvider:
    profile = os.getenv("IMAGE_INTELLIGENCE_PROFILE", "deterministic").lower()
    app_env = os.getenv("APP_ENV", "development").lower()
    if profile == "deterministic":
        if app_env in {"production", "prod"}:
            raise RuntimeError("deterministic image intelligence is forbidden in production")
        return DeterministicImageFeatureAdapter()
    raise RuntimeError(f"image intelligence provider is not registered: {profile}")
