import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol


TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]", re.IGNORECASE)

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
