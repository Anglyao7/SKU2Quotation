from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.file_scanner import get_file_scanner
from ..adapters.image_intelligence import get_image_intelligence_provider
from ..adapters.object_storage import get_object_storage
from ..domain.errors import ApplicationError
from ..image_intelligence_models import ImageEmbeddingRow, ImageSearchRow, VisionObservationRow
from ..image_intelligence_schemas import ImageProjectionResponse, ImageSearchResponse, ImageSearchResult
from ..repositories import image_intelligence_repository as repository
from ..services.embedding import validate_vectors
from ..model_mixins import utcnow


def _require(permissions: frozenset[str], code: str) -> None:
    if code not in permissions:
        raise ApplicationError("PERMISSION_DENIED", f"Permission is required: {code}", kind="forbidden")


def _projection_response(embedding: ImageEmbeddingRow, observation: VisionObservationRow, *, idempotent: bool) -> ImageProjectionResponse:
    return ImageProjectionResponse(observation_id=observation.id, embedding_id=embedding.id, product_id=embedding.product_id, product_image_id=embedding.product_image_id, model_provider=embedding.model_provider, model_name=embedding.model_name, model_version=embedding.model_version, dimensions=embedding.dimensions, quality_score=float(embedding.quality_score), labels=observation.labels, risks=observation.risks, idempotent=idempotent)


def project_product_image(session: Session, *, tenant_id: UUID, permissions: frozenset[str], image_id: UUID) -> ImageProjectionResponse:
    _require(permissions, "product.edit")
    pair = repository.get_product_image(session, tenant_id=tenant_id, image_id=image_id)
    if pair is None:
        raise ApplicationError("PRODUCT_IMAGE_NOT_FOUND", "Product image was not found.", kind="not_found")
    image, product = pair
    if image.approval_status != "APPROVED":
        raise ApplicationError("IMAGE_NOT_APPROVED", "Only APPROVED product images can enter the active similarity corpus.", kind="conflict")
    provider = get_image_intelligence_provider()
    existing = repository.get_projection(session, tenant_id=tenant_id, image_id=image.id, provider=provider.identity.provider, model=provider.identity.model_name, version=provider.identity.model_version, content_hash=image.sha256)
    if existing:
        return _projection_response(existing[0], existing[1], idempotent=True)
    storage = get_object_storage()
    try:
        with storage.materialize(image.object_key) as path:
            content = path.read_bytes()
    except FileNotFoundError as exc:
        raise ApplicationError("IMAGE_OBJECT_MISSING", "The approved image object is missing.", kind="conflict") from exc
    if hashlib.sha256(content).hexdigest() != image.sha256:
        raise ApplicationError("IMAGE_HASH_MISMATCH", "The image object no longer matches its authoritative hash.", kind="conflict")
    result = provider.analyze(content, content_type=image.content_type)
    validate_vectors([result.embedding], expected_count=1, dimensions=provider.identity.dimensions)
    now = utcnow()
    for row in session.scalars(select(ImageEmbeddingRow).where(ImageEmbeddingRow.tenant_id == tenant_id, ImageEmbeddingRow.product_image_id == image.id, ImageEmbeddingRow.model_provider == provider.identity.provider, ImageEmbeddingRow.model_name == provider.identity.model_name, ImageEmbeddingRow.model_version == provider.identity.model_version, ImageEmbeddingRow.status == "ACTIVE")).all():
        row.status = "STALE"; row.superseded_at = now
    observation = VisionObservationRow(tenant_id=tenant_id, product_image_id=image.id, product_id=product.id, content_hash=image.sha256, model_provider=provider.identity.provider, model_name=provider.identity.model_name, model_version=provider.identity.model_version, labels=result.labels, risks=result.risks, quality_score=Decimal(str(result.quality_score)), status="OBSERVED")
    embedding = ImageEmbeddingRow(tenant_id=tenant_id, product_image_id=image.id, product_id=product.id, product_version=product.current_version, content_hash=image.sha256, model_provider=provider.identity.provider, model_name=provider.identity.model_name, model_version=provider.identity.model_version, dimensions=provider.identity.dimensions, distance_metric=provider.identity.distance_metric, embedding=result.embedding, quality_score=Decimal(str(result.quality_score)), permission_scope={"classification": "INTERNAL", "approved_media_only": True}, status="ACTIVE", activated_at=now)
    session.add_all([observation, embedding]); session.commit()
    return _projection_response(embedding, observation, idempotent=False)


def _validated_image_type(content: bytes, declared: str) -> str:
    signatures = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif"), (b"RIFF", "image/webp"))
    for signature, content_type in signatures:
        if content.startswith(signature):
            if content_type == "image/webp" and content[8:12] != b"WEBP":
                continue
            return content_type
    raise ApplicationError("IMAGE_FORMAT_INVALID", f"Unsupported or invalid image payload ({declared}).")


def search_by_image(session: Session, *, tenant_id: UUID, membership_id: UUID, permissions: frozenset[str], filename: str, declared_content_type: str, content: bytes, limit: int) -> ImageSearchResponse:
    _require(permissions, "product.view")
    if not content or len(content) > int(os.getenv("IMAGE_SEARCH_MAX_BYTES", str(20 * 1024 * 1024))):
        raise ApplicationError("IMAGE_SIZE_INVALID", "Query image must be between 1 byte and 20 MB.")
    content_type = _validated_image_type(content, declared_content_type)
    provider = get_image_intelligence_provider()
    now = utcnow(); storage = get_object_storage()
    for expired in repository.list_expired_searches(session, tenant_id=tenant_id, now=now):
        storage.delete(expired.query_object_key); expired.status = "EXPIRED"; expired.query_embedding = None
    search_id = uuid4(); suffix = Path(filename).suffix.lower() or ".img"
    quarantine = f"tenants/{tenant_id}/quarantine/image-search/{search_id}{suffix}"
    source = f"tenants/{tenant_id}/query-images/{search_id}{suffix}"
    descriptor, raw_path = tempfile.mkstemp(prefix="atc-image-search-", suffix=suffix); os.close(descriptor); path = Path(raw_path)
    try:
        path.write_bytes(content); storage.put_file(path, object_key=quarantine, content_type=content_type)
        scan = get_file_scanner().scan(path)
        if not scan.clean:
            storage.delete(quarantine)
            raise ApplicationError("IMAGE_SECURITY_REJECTED", "Query image failed the malware scan.", kind="forbidden")
        storage.promote(quarantine_key=quarantine, source_key=source)
    finally:
        path.unlink(missing_ok=True)
    try:
        result = provider.analyze(content, content_type=content_type)
    except Exception:
        storage.delete(source)
        raise
    validate_vectors([result.embedding], expected_count=1, dimensions=provider.identity.dimensions)
    ranked: list[ImageSearchResult] = []
    for candidate in repository.search_active_corpus(session, tenant_id=tenant_id, provider=provider.identity.provider, model=provider.identity.model_name, version=provider.identity.model_version, query_vector=result.embedding, limit=max(limit * 3, 25)):
        similarity = float(candidate["similarity"])
        if similarity < 0.60:
            continue
        ranked.append(ImageSearchResult(product_id=UUID(str(candidate["product_id"])), product_image_id=UUID(str(candidate["product_image_id"])), product_name=str(candidate["product_name"]), product_code=str(candidate["product_code"]) if candidate["product_code"] else None, visual_similarity=round(similarity, 6), classification="POSSIBLE_SAME_ITEM" if similarity >= 0.985 else "VISUALLY_SIMILAR", evidence={"query_hash": hashlib.sha256(content).hexdigest(), "corpus_hash": str(candidate["content_hash"]), "quality_score": float(candidate["quality_score"]), "model_version": provider.identity.model_version}, conflicts=[]))
    ranked.sort(key=lambda item: item.visual_similarity, reverse=True)
    deduped: list[ImageSearchResult] = []
    seen: set[UUID] = set()
    for item in ranked:
        if item.product_id not in seen:
            deduped.append(item); seen.add(item.product_id)
        if len(deduped) >= limit:
            break
    warnings = ["Visual similarity is non-deterministic evidence and never proves an identical item."]
    if provider.identity.provider == "local":
        warnings.append("Development feature adapter: production model quality is not asserted.")
    status = "COMPLETED" if deduped else "NO_RELIABLE_MATCH"
    expires_at = now + timedelta(hours=int(os.getenv("IMAGE_SEARCH_TTL_HOURS", "24")))
    row = ImageSearchRow(id=search_id, tenant_id=tenant_id, requested_by_membership_id=membership_id, query_object_key=source, query_hash=hashlib.sha256(content).hexdigest(), model_provider=provider.identity.provider, model_name=provider.identity.model_name, model_version=provider.identity.model_version, dimensions=provider.identity.dimensions, query_embedding=result.embedding, result_snapshot=[item.model_dump(mode="json") for item in deduped], warnings=warnings, status=status, expires_at=expires_at)
    session.add(row); session.commit()
    return ImageSearchResponse(id=row.id, status=status, model_provider=row.model_provider, model_name=row.model_name, model_version=row.model_version, ranking_version="image-fusion-v1", expires_at=row.expires_at, warnings=warnings, results=deduped)
