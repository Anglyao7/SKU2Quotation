from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..services.embedding import EmbeddingIdentity


@dataclass(frozen=True)
class VisionResult:
    labels: list[dict[str, object]]
    risks: list[dict[str, object]]
    quality_score: float
    embedding: list[float]


class ImageIntelligenceProvider(Protocol):
    identity: EmbeddingIdentity

    def analyze(self, content: bytes, *, content_type: str) -> VisionResult: ...
