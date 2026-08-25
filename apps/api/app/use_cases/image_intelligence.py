from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
import psycopg
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..adapters.image_intelligence import (
    ImageIntelligenceProviderError,
    ImageIntelligenceUnavailable,
)
from ..adapters.object_storage import get_object_storage
from ..database import SessionLocal, set_request_context
from ..domain.errors import ApplicationError
from ..image_intelligence_models import (
    ImageEmbeddingRow,
    ImageIndexJobRow,
    ImageSearchRow,
    VisionObservationRow,
)
from ..image_intelligence_schemas import (
    ImageIndexJobResponse,
    ImageIndexJobStartRequest,
    ImageIndexStatusResponse,
    ImageProjectionResponse,
    ImageSearchResponse,
    ImageSearchResult,
)
from ..model_mixins import utcnow
from ..ports.image_intelligence import ImageIntelligenceProvider
from ..repositories import image_intelligence_repository as repository
from ..services.auth.dependencies import RequestContext
from ..services.embedding import validate_vectors
from ..services.external_image_migration import (
    ImageMigrationError,
    SourcePolicy,
    download_image,
)
from ..services.image_embedding_configuration import (
    resolved_image_embedding_provider,
    resolved_image_index_concurrency,
)


logger = logging.getLogger(__name__)


def _bounded_index_concurrency(
    environment_name: str,
    *,
    default: int,
    maximum: int,
) -> int:
    raw_value = os.getenv(environment_name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError:
        logger.warning(
            "%s=%r is invalid; using %s",
            environment_name,
            raw_value,
            default,
        )
        return default
    return max(1, min(maximum, value))


_IMAGE_INDEX_GLOBAL_CONCURRENCY = _bounded_index_concurrency(
    "IMAGE_INDEX_GLOBAL_CONCURRENCY",
    default=32,
    maximum=64,
)
_image_index_executor = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="image-index",
)
_image_index_projection_executor = ThreadPoolExecutor(
    max_workers=_IMAGE_INDEX_GLOBAL_CONCURRENCY,
    thread_name_prefix="image-projection",
)
_stale_job_after = timedelta(minutes=10)
_ZERO_IDENTITY = UUID(int=0)


@dataclass(frozen=True, slots=True)
class PublicImageMatch:
    product_id: UUID
    product_image_id: UUID
    similarity: float
    match_percent: float
    confidence: str


def _require(permissions: frozenset[str], code: str) -> None:
    if code not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            f"Permission is required: {code}",
            kind="forbidden",
        )


def _provider(session: Session) -> ImageIntelligenceProvider:
    try:
        return resolved_image_embedding_provider(session)
    except (
        ImageIntelligenceUnavailable,
        ImageIntelligenceProviderError,
        ValueError,
    ) as exc:
        raise ApplicationError(
            "IMAGE_INTELLIGENCE_UNAVAILABLE",
            str(exc) or "图片搜索模型尚未配置。",
            kind="unavailable",
        ) from exc


def _projection_response(
    embedding: ImageEmbeddingRow,
    observation: VisionObservationRow,
    *,
    idempotent: bool,
) -> ImageProjectionResponse:
    return ImageProjectionResponse(
        product_id=embedding.product_id,
        product_image_id=embedding.product_image_id,
        quality_score=float(embedding.quality_score),
        labels=observation.labels,
        risks=observation.risks,
        idempotent=idempotent,
    )


def _download_public_image(source_url: str):
    try:
        with tempfile.TemporaryDirectory(prefix="atc-image-index-") as directory:
            target = Path(directory) / "source-image"
            with httpx.Client(
                timeout=httpx.Timeout(30.0, connect=8.0),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                metadata = download_image(
                    client,
                    source_url=source_url,
                    destination=target,
                    policy=SourcePolicy((), allow_all_public_hosts=True),
                    max_bytes=int(
                        os.getenv(
                            "IMAGE_SEARCH_MAX_BYTES",
                            str(20 * 1024 * 1024),
                        )
                    ),
                    max_pixels=50_000_000,
                    max_redirects=4,
                )
            return target.read_bytes(), metadata
    except (ImageMigrationError, httpx.HTTPError, OSError) as exc:
        error_code = getattr(exc, "code", type(exc).__name__)
        raise ApplicationError(
            "IMAGE_REMOTE_OBJECT_UNAVAILABLE",
            f"商品图片地址暂时无法读取（{error_code}）。",
            kind="unavailable",
        ) from exc


def _materialize_approved_image(image) -> tuple[bytes, str]:
    object_key = str(image.object_key or "").strip()
    if object_key.startswith(("https://", "http://")):
        content, metadata = _download_public_image(object_key)

        # Legacy imports stored a source-record digest instead of the actual
        # object digest. Repair that metadata once the public R2/CDN object has
        # been downloaded and validated so future incremental runs can skip it.
        image.sha256 = metadata.sha256
        image.byte_size = metadata.byte_size
        image.content_type = metadata.content_type
        image.width = metadata.width
        image.height = metadata.height
        return content, metadata.sha256

    storage_error: Exception | None = None
    try:
        with get_object_storage().materialize(object_key) as path:
            content = path.read_bytes()
    except Exception as exc:
        storage_error = exc
        media_base_url = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip().rstrip("/")
        if not media_base_url:
            raise ApplicationError(
                "IMAGE_OBJECT_MISSING",
                "R2 中的商品图片对象不存在或暂时无法读取。",
                kind="conflict",
            ) from exc
        public_url = (
            f"{media_base_url}/{quote(object_key.lstrip('/'), safe='/')}"
        )
        try:
            content, _metadata = _download_public_image(public_url)
        except ApplicationError as cdn_exc:
            raise ApplicationError(
                "IMAGE_OBJECT_MISSING",
                "商品图片在 R2 和公共 CDN 中均无法读取。",
                kind="conflict",
            ) from cdn_exc
        logger.info(
            "image index used public CDN fallback for object %s after storage error %s",
            object_key,
            type(storage_error).__name__,
        )
    content_hash = hashlib.sha256(content).hexdigest()
    if content_hash != image.sha256:
        raise ApplicationError(
            "IMAGE_HASH_MISMATCH",
            "R2 图片内容与商品图片记录不一致。",
            kind="conflict",
        )
    return content, content_hash


def _project_product_image(
    session: Session,
    *,
    tenant_id: UUID,
    image_id: UUID,
    provider: ImageIntelligenceProvider,
    force: bool = False,
) -> tuple[ImageEmbeddingRow, VisionObservationRow, bool]:
    pair = repository.get_product_image(
        session,
        tenant_id=tenant_id,
        image_id=image_id,
    )
    if pair is None:
        raise ApplicationError(
            "PRODUCT_IMAGE_NOT_FOUND",
            "商品图片不存在。",
            kind="not_found",
        )
    image, product = pair
    if image.approval_status != "APPROVED" or product.status != "ACTIVE":
        raise ApplicationError(
            "IMAGE_NOT_APPROVED",
            "只有已审批且商品有效的图片才能进入图片搜索索引。",
            kind="conflict",
        )
    identity = provider.identity
    content: bytes | None = None
    content_hash = image.sha256
    if str(image.object_key or "").strip().startswith(("https://", "http://")):
        content, content_hash = _materialize_approved_image(image)
    existing = repository.get_projection(
        session,
        tenant_id=tenant_id,
        image_id=image.id,
        provider=identity.provider,
        model=identity.model_name,
        version=identity.model_version,
        content_hash=content_hash,
    )
    if (
        existing
        and not force
        and existing[0].status == "ACTIVE"
        and existing[0].dimensions == identity.dimensions
    ):
        if existing[0].product_version != product.current_version:
            existing[0].product_version = product.current_version
            existing[0].updated_at = utcnow()
            session.flush()
        return existing[0], existing[1], True

    if content is None:
        content, content_hash = _materialize_approved_image(image)
    try:
        result = provider.analyze(content, content_type=image.content_type)
    except ImageIntelligenceProviderError as exc:
        raise ApplicationError(
            "IMAGE_EMBEDDING_FAILED",
            str(exc),
            kind="unavailable",
        ) from exc
    validate_vectors(
        [result.embedding],
        expected_count=1,
        dimensions=identity.dimensions,
    )
    now = utcnow()
    active_rows = session.scalars(
        select(ImageEmbeddingRow).where(
            ImageEmbeddingRow.tenant_id == tenant_id,
            ImageEmbeddingRow.product_image_id == image.id,
            ImageEmbeddingRow.status == "ACTIVE",
            ImageEmbeddingRow.deleted_at.is_(None),
        )
    ).all()
    for row in active_rows:
        if existing is None or row.id != existing[0].id:
            row.status = "STALE"
            row.superseded_at = now

    quality = Decimal(str(round(result.quality_score, 4)))
    if existing is None:
        observation = VisionObservationRow(
            tenant_id=tenant_id,
            product_image_id=image.id,
            product_id=product.id,
            content_hash=content_hash,
            model_provider=identity.provider,
            model_name=identity.model_name,
            model_version=identity.model_version,
            labels=result.labels,
            risks=result.risks,
            quality_score=quality,
            status="OBSERVED",
        )
        embedding = ImageEmbeddingRow(
            tenant_id=tenant_id,
            product_image_id=image.id,
            product_id=product.id,
            product_version=product.current_version,
            content_hash=content_hash,
            model_provider=identity.provider,
            model_name=identity.model_name,
            model_version=identity.model_version,
            dimensions=identity.dimensions,
            distance_metric=identity.distance_metric,
            embedding=result.embedding,
            quality_score=quality,
            permission_scope={
                "classification": "TENANT",
                "approved_media_only": True,
                "public_search_requires_published_offer": True,
            },
            status="ACTIVE",
            activated_at=now,
        )
        session.add_all([observation, embedding])
    else:
        embedding, observation = existing
        embedding.product_id = product.id
        embedding.product_version = product.current_version
        embedding.dimensions = identity.dimensions
        embedding.embedding = result.embedding
        embedding.quality_score = quality
        embedding.permission_scope = {
            "classification": "TENANT",
            "approved_media_only": True,
            "public_search_requires_published_offer": True,
        }
        embedding.status = "ACTIVE"
        embedding.activated_at = now
        embedding.superseded_at = None
        embedding.updated_at = now
        observation.labels = result.labels
        observation.risks = result.risks
        observation.quality_score = quality
        observation.status = "OBSERVED"
        observation.updated_at = now
    session.flush()
    return embedding, observation, False


def project_product_image(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    image_id: UUID,
) -> ImageProjectionResponse:
    _require(permissions, "product.edit")
    try:
        embedding, observation, idempotent = _project_product_image(
            session,
            tenant_id=tenant_id,
            image_id=image_id,
            provider=_provider(session),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _projection_response(
        embedding,
        observation,
        idempotent=idempotent,
    )


def _validated_image_type(content: bytes, declared: str) -> str:
    signatures = (
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"GIF87a", "image/gif"),
        (b"GIF89a", "image/gif"),
        (b"RIFF", "image/webp"),
    )
    for signature, content_type in signatures:
        if content.startswith(signature):
            if content_type == "image/webp" and content[8:12] != b"WEBP":
                continue
            return content_type
    raise ApplicationError(
        "IMAGE_FORMAT_INVALID",
        f"不支持或无效的图片格式（{declared}）。",
    )


def _validate_query_image(content: bytes, declared_content_type: str) -> str:
    max_bytes = int(
        os.getenv("IMAGE_SEARCH_MAX_BYTES", str(20 * 1024 * 1024))
    )
    if not content or len(content) > max_bytes:
        raise ApplicationError(
            "IMAGE_SIZE_INVALID",
            "搜索图片大小必须在 1 字节到 20 MB 之间。",
        )
    return _validated_image_type(content, declared_content_type)


def _rank_image_results(
    candidates: list[dict[str, object]],
    *,
    limit: int,
) -> list[ImageSearchResult]:
    ranked: list[ImageSearchResult] = []
    for candidate in candidates:
        similarity = max(-1.0, min(1.0, float(candidate["similarity"])))
        ranked.append(
            ImageSearchResult(
                product_id=UUID(str(candidate["product_id"])),
                product_image_id=UUID(str(candidate["product_image_id"])),
                product_name=str(candidate["product_name"]),
                product_code=(
                    str(candidate["product_code"])
                    if candidate["product_code"]
                    else None
                ),
                visual_similarity=round(similarity, 6),
                classification=(
                    "POSSIBLE_SAME_ITEM"
                    if similarity >= 0.92
                    else "VISUALLY_SIMILAR"
                ),
                conflicts=[],
            )
        )
    ranked.sort(key=lambda item: item.visual_similarity, reverse=True)
    deduped: list[ImageSearchResult] = []
    seen: set[UUID] = set()
    for item in ranked:
        if item.product_id in seen:
            continue
        seen.add(item.product_id)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def search_by_image(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    filename: str,
    declared_content_type: str,
    content: bytes,
    limit: int,
) -> ImageSearchResponse:
    _require(permissions, "product.view")
    content_type = _validate_query_image(content, declared_content_type)
    provider = _provider(session)
    now = utcnow()
    storage = get_object_storage()
    for expired in repository.list_expired_searches(
        session,
        tenant_id=tenant_id,
        now=now,
    ):
        storage.delete(expired.query_object_key)
        expired.status = "EXPIRED"
        expired.query_embedding = None

    search_id = uuid4()
    suffix = Path(filename).suffix.lower() or ".img"
    quarantine = f"tenants/{tenant_id}/quarantine/image-search/{search_id}{suffix}"
    source = f"tenants/{tenant_id}/query-images/{search_id}{suffix}"
    descriptor, raw_path = tempfile.mkstemp(
        prefix="atc-image-search-",
        suffix=suffix,
    )
    os.close(descriptor)
    path = Path(raw_path)
    try:
        path.write_bytes(content)
        storage.put_file(
            path,
            object_key=quarantine,
            content_type=content_type,
        )
        storage.promote(quarantine_key=quarantine, source_key=source)
    finally:
        path.unlink(missing_ok=True)
    try:
        result = provider.analyze(content, content_type=content_type)
    except Exception:
        storage.delete(source)
        raise
    validate_vectors(
        [result.embedding],
        expected_count=1,
        dimensions=provider.identity.dimensions,
    )
    candidates = repository.search_active_corpus(
        session,
        tenant_id=tenant_id,
        provider=provider.identity.provider,
        model=provider.identity.model_name,
        version=provider.identity.model_version,
        dimensions=provider.identity.dimensions,
        query_vector=result.embedding,
        limit=max(limit * 3, 25),
    )
    deduped = _rank_image_results(candidates, limit=limit)
    warnings = [
        "Visual similarity is non-deterministic evidence and never proves an identical item."
    ]
    if provider.identity.provider == "local":
        warnings.append(
            "Development feature adapter: production model quality is not asserted."
        )
    status = "COMPLETED" if deduped else "NO_RELIABLE_MATCH"
    expires_at = now + timedelta(
        hours=int(os.getenv("IMAGE_SEARCH_TTL_HOURS", "24"))
    )
    row = ImageSearchRow(
        id=search_id,
        tenant_id=tenant_id,
        requested_by_membership_id=membership_id,
        query_object_key=source,
        query_hash=hashlib.sha256(content).hexdigest(),
        model_provider=provider.identity.provider,
        model_name=provider.identity.model_name,
        model_version=provider.identity.model_version,
        dimensions=provider.identity.dimensions,
        query_embedding=result.embedding,
        result_snapshot=[item.model_dump(mode="json") for item in deduped],
        warnings=warnings,
        status=status,
        expires_at=expires_at,
    )
    session.add(row)
    session.commit()
    return ImageSearchResponse(
        id=row.id,
        status=status,
        expires_at=row.expires_at,
        warnings=warnings,
        results=deduped,
    )


def search_public_image_matches(
    session: Session,
    *,
    tenant_id: UUID,
    declared_content_type: str,
    content: bytes,
    limit: int,
    allowed_product_ids: set[UUID] | None = None,
    category: str | None = None,
    timings: dict[str, float] | None = None,
) -> list[PublicImageMatch]:
    """Search only current published offers and never persist visitor images."""

    started = time.perf_counter()
    content_type = _validate_query_image(content, declared_content_type)
    if timings is not None:
        timings["validate"] = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    provider = _provider(session)
    identity = provider.identity
    if timings is not None:
        timings["provider"] = (time.perf_counter() - started) * 1000

    now = utcnow()
    started = time.perf_counter()
    if not repository.has_active_corpus(
        session,
        tenant_id=tenant_id,
        provider=identity.provider,
        model=identity.model_name,
        version=identity.model_version,
        dimensions=identity.dimensions,
        published_only=True,
        allowed_product_ids=allowed_product_ids,
        category=category,
        now=now,
    ):
        if timings is not None:
            timings["corpus"] = (time.perf_counter() - started) * 1000
        return []
    if timings is not None:
        timings["corpus"] = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    try:
        result = provider.analyze(content, content_type=content_type)
    except ImageIntelligenceProviderError as exc:
        raise ApplicationError(
            "PUBLIC_IMAGE_SEARCH_UNAVAILABLE",
            str(exc),
            kind="unavailable",
        ) from exc
    if timings is not None:
        timings["embedding"] = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    candidates = repository.search_active_corpus(
        session,
        tenant_id=tenant_id,
        provider=identity.provider,
        model=identity.model_name,
        version=identity.model_version,
        dimensions=identity.dimensions,
        query_vector=result.embedding,
        limit=max(limit * 4, 40),
        published_only=True,
        allowed_product_ids=allowed_product_ids,
        category=category,
        now=now,
    )
    if timings is not None:
        timings["vector"] = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    matches: list[PublicImageMatch] = []
    seen: set[UUID] = set()
    for candidate in candidates:
        product_id = UUID(str(candidate["product_id"]))
        if product_id in seen:
            continue
        seen.add(product_id)
        similarity = max(-1.0, min(1.0, float(candidate["similarity"])))
        match_percent = round(max(0.0, similarity) * 100, 1)
        confidence = (
            "HIGH"
            if similarity >= 0.75
            else "MEDIUM"
            if similarity >= 0.5
            else "REFERENCE"
        )
        matches.append(
            PublicImageMatch(
                product_id=product_id,
                product_image_id=UUID(str(candidate["product_image_id"])),
                similarity=round(similarity, 6),
                match_percent=match_percent,
                confidence=confidence,
            )
        )
        if len(matches) >= limit:
            break
    if timings is not None:
        timings["rank"] = (time.perf_counter() - started) * 1000
    return matches


def _remaining_image_ids(job: ImageIndexJobRow) -> list[UUID]:
    values: list[UUID] = []
    for raw in job.remaining_image_ids or []:
        try:
            values.append(UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    return list(dict.fromkeys(values))


def _job_response(job: ImageIndexJobRow) -> ImageIndexJobResponse:
    progress = (
        100.0
        if job.total_images == 0 and job.status == "SUCCEEDED"
        else 0.0
        if job.total_images == 0
        else min(100.0, round(job.processed_images / job.total_images * 100, 1))
    )
    remaining = len(_remaining_image_ids(job))
    if remaining == 0 and job.processed_images < job.total_images:
        remaining = job.total_images - job.processed_images
    return ImageIndexJobResponse(
        id=job.id,
        mode=job.mode,
        status=job.status,
        total_images=job.total_images,
        processed_images=job.processed_images,
        failed_images=job.failed_images,
        embeddings=job.embeddings,
        remaining_images=remaining,
        progress_percent=progress,
        current_image_id=job.current_image_id,
        current_product_name=job.current_product_name,
        error_message=job.error_message,
        pause_requested=(
            job.status in {"QUEUED", "RUNNING"}
            and job.pause_requested_at is not None
        ),
        pause_requested_at=job.pause_requested_at,
        paused_at=job.paused_at,
        resumable=job.status in {"PAUSED", "FAILED"},
        checkpoint_at=(
            job.updated_at
            if job.started_at is not None or job.processed_images > 0
            else None
        ),
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _active_job(session: Session, *, tenant_id: UUID) -> ImageIndexJobRow | None:
    return session.scalar(
        select(ImageIndexJobRow)
        .where(
            ImageIndexJobRow.tenant_id == tenant_id,
            ImageIndexJobRow.status.in_(("QUEUED", "RUNNING", "PAUSED")),
            ImageIndexJobRow.deleted_at.is_(None),
        )
        .order_by(ImageIndexJobRow.created_at.desc())
        .limit(1)
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _expire_stale_job(session: Session, *, tenant_id: UUID) -> None:
    active = _active_job(session, tenant_id=tenant_id)
    if active is None or active.status == "PAUSED":
        return
    if _as_utc(active.updated_at) >= utcnow() - _stale_job_after:
        return
    active.status = "PAUSED"
    active.error_message = "图片索引服务曾中断，已保存断点，可继续向量化。"
    active.current_image_id = None
    active.current_product_name = None
    active.pause_requested_at = None
    active.paused_at = utcnow()
    active.completed_at = None
    session.commit()


def get_image_index_status(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
) -> ImageIndexStatusResponse:
    _require(permissions, "product.view")
    provider = _provider(session)
    return ImageIndexStatusResponse(
        **repository.image_index_status(
            session,
            tenant_id=tenant_id,
            provider=provider.identity.provider,
            model=provider.identity.model_name,
            version=provider.identity.model_version,
            dimensions=provider.identity.dimensions,
        )
    )


def latest_image_index_job(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
) -> ImageIndexJobResponse | None:
    _require(permissions, "product.view")
    _expire_stale_job(session, tenant_id=tenant_id)
    job = session.scalar(
        select(ImageIndexJobRow)
        .where(ImageIndexJobRow.tenant_id == tenant_id)
        .order_by(ImageIndexJobRow.created_at.desc())
        .limit(1)
    )
    return _job_response(job) if job is not None else None


def _managed_job(
    session: Session,
    *,
    tenant_id: UUID,
    job_id: UUID,
    for_update: bool = False,
) -> ImageIndexJobRow:
    statement = select(ImageIndexJobRow).where(
        ImageIndexJobRow.tenant_id == tenant_id,
        ImageIndexJobRow.id == job_id,
    )
    if for_update:
        statement = statement.with_for_update()
    job = session.scalar(statement)
    if job is None:
        raise ApplicationError(
            "IMAGE_INDEX_JOB_NOT_FOUND",
            "图片向量化任务不存在。",
            kind="not_found",
        )
    return job


def get_image_index_job(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    job_id: UUID,
) -> ImageIndexJobResponse:
    _require(permissions, "product.view")
    _expire_stale_job(session, tenant_id=tenant_id)
    return _job_response(
        _managed_job(session, tenant_id=tenant_id, job_id=job_id)
    )


def _pause_at_checkpoint(session: Session, job: ImageIndexJobRow) -> bool:
    session.refresh(job, attribute_names=("status", "pause_requested_at", "updated_at"))
    if job.status == "PAUSED":
        return True
    if job.status != "RUNNING":
        return True
    if job.pause_requested_at is None:
        return False
    now = utcnow()
    job.status = "PAUSED"
    job.paused_at = now
    job.current_image_id = None
    job.current_product_name = None
    job.updated_at = now
    session.commit()
    return True


def _safe_job_error(exc: Exception) -> str:
    if isinstance(exc, ApplicationError):
        return exc.safe_message
    if isinstance(exc, (ImageIntelligenceProviderError, ValueError)):
        return str(exc)
    return "图片向量化失败，请检查模型配置、R2 对象或服务日志。"


def _project_image_index_target(
    *,
    organization_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    image_id: UUID,
    provider: ImageIntelligenceProvider,
    force: bool,
) -> bool:
    """Project one image in a thread-owned transaction.

    SQLAlchemy sessions are never shared across workers. The configured image
    providers are immutable after construction; Qwen requests share only the
    thread-safe pooled HTTP client.
    """

    with SessionLocal() as worker_session:
        set_request_context(
            worker_session,
            organization_id=organization_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        try:
            _embedding, _observation, idempotent = _project_product_image(
                worker_session,
                tenant_id=tenant_id,
                image_id=image_id,
                provider=provider,
                force=force,
            )
            worker_session.commit()
            return idempotent
        except Exception:
            worker_session.rollback()
            raise


def _run_image_index_job(
    *,
    job_id: UUID,
    organization_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
) -> None:
    with SessionLocal() as session:
        set_request_context(
            session,
            organization_id=organization_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        job = session.scalar(
            select(ImageIndexJobRow)
            .where(
                ImageIndexJobRow.tenant_id == tenant_id,
                ImageIndexJobRow.id == job_id,
                ImageIndexJobRow.status == "QUEUED",
            )
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return
        try:
            provider = _provider(session)
            identity = provider.identity
            identity_changed = (
                job.model_provider,
                job.model_name,
                job.model_version,
                job.dimensions,
            ) != (
                identity.provider,
                identity.model_name,
                identity.model_version,
                identity.dimensions,
            )
            stored_remaining = _remaining_image_ids(job)
            base_processed = 0 if identity_changed else job.processed_images
            base_embeddings = 0 if identity_changed else job.embeddings
            if identity_changed:
                targets = repository.list_index_target_images(
                    session,
                    tenant_id=tenant_id,
                    provider=identity.provider,
                    model=identity.model_name,
                    version=identity.model_version,
                    dimensions=identity.dimensions,
                    full_rebuild=job.mode == "FULL_REBUILD",
                )
            elif stored_remaining:
                targets = repository.list_index_target_images(
                    session,
                    tenant_id=tenant_id,
                    provider=identity.provider,
                    model=identity.model_name,
                    version=identity.model_version,
                    dimensions=identity.dimensions,
                    full_rebuild=True,
                    image_ids=stored_remaining,
                )
                target_ids = {image_id for image_id, _ in targets}
                newly_pending = repository.list_index_target_images(
                    session,
                    tenant_id=tenant_id,
                    provider=identity.provider,
                    model=identity.model_name,
                    version=identity.model_version,
                    dimensions=identity.dimensions,
                    full_rebuild=False,
                )
                targets.extend(
                    item for item in newly_pending if item[0] not in target_ids
                )
            else:
                targets = repository.list_index_target_images(
                    session,
                    tenant_id=tenant_id,
                    provider=identity.provider,
                    model=identity.model_name,
                    version=identity.model_version,
                    dimensions=identity.dimensions,
                    full_rebuild=False,
                )
            target_ids = [image_id for image_id, _ in targets]
            job.status = "RUNNING"
            if job.started_at is None:
                job.started_at = utcnow()
            job.model_provider = identity.provider
            job.model_name = identity.model_name
            job.model_version = identity.model_version
            job.dimensions = identity.dimensions
            job.processed_images = base_processed
            job.embeddings = base_embeddings
            job.total_images = base_processed + len(target_ids)
            job.remaining_image_ids = [str(value) for value in target_ids]
            job.failed_images = 0
            job.error_message = None
            job.paused_at = None
            job.completed_at = None
            session.commit()
            if _pause_at_checkpoint(session, job):
                return

            concurrency = min(
                resolved_image_index_concurrency(session),
                _IMAGE_INDEX_GLOBAL_CONCURRENCY,
                max(1, len(targets)),
            )
            completed_ids: set[UUID] = set()
            embeddings_written = 0
            logger.info(
                "image index job %s processing %s images with concurrency=%s",
                job_id,
                len(targets),
                concurrency,
            )
            for batch_start in range(0, len(targets), concurrency):
                if _pause_at_checkpoint(session, job):
                    return
                batch = targets[batch_start : batch_start + concurrency]
                job.current_image_id = batch[0][0]
                job.current_product_name = (
                    batch[0][1]
                    if len(batch) == 1
                    else f"{batch[0][1]} 等 {len(batch)} 张图片"
                )[:500]
                job.updated_at = utcnow()
                session.commit()

                futures = [
                    (
                        image_id,
                        product_name,
                        _image_index_projection_executor.submit(
                            _project_image_index_target,
                            organization_id=organization_id,
                            tenant_id=tenant_id,
                            user_id=user_id,
                            image_id=image_id,
                            provider=provider,
                            force=job.mode == "FULL_REBUILD",
                        ),
                    )
                    for image_id, product_name in batch
                ]
                batch_failures: list[tuple[UUID, str, Exception]] = []
                for image_id, product_name, future in futures:
                    try:
                        idempotent = future.result()
                    except Exception as exc:
                        logger.exception(
                            "image index job %s failed image %s",
                            job_id,
                            image_id,
                        )
                        batch_failures.append((image_id, product_name, exc))
                    else:
                        completed_ids.add(image_id)
                        if not idempotent:
                            embeddings_written += 1

                job.processed_images = base_processed + len(completed_ids)
                job.embeddings = base_embeddings + embeddings_written
                job.remaining_image_ids = [
                    str(value)
                    for value in target_ids
                    if value not in completed_ids
                ]
                job.updated_at = utcnow()

                if batch_failures:
                    failed_image_id, failed_product_name, failure = batch_failures[0]
                    job.status = "FAILED"
                    job.failed_images = len(batch_failures)
                    job.current_image_id = failed_image_id
                    job.current_product_name = failed_product_name
                    job.error_message = (
                        f"{_safe_job_error(failure)} "
                        "已完成的图片向量和断点均已保留。"
                    )
                    job.pause_requested_at = None
                    job.paused_at = None
                    job.completed_at = utcnow()
                    session.commit()
                    return

                job.current_image_id = None
                job.current_product_name = None
                session.commit()
                if _pause_at_checkpoint(session, job):
                    return

            session.refresh(job)
            if job.pause_requested_at is not None:
                job.status = "PAUSED"
                job.paused_at = utcnow()
            elif job.status == "RUNNING":
                job.status = "SUCCEEDED"
                job.processed_images = job.total_images
                job.remaining_image_ids = []
                job.pause_requested_at = None
                job.paused_at = None
                job.error_message = None
                job.completed_at = utcnow()
            session.commit()
        except Exception as exc:
            logger.exception("image index job %s failed", job_id)
            session.rollback()
            failed = session.scalar(
                select(ImageIndexJobRow).where(
                    ImageIndexJobRow.tenant_id == tenant_id,
                    ImageIndexJobRow.id == job_id,
                )
            )
            if failed is None:
                return
            failed.status = "FAILED"
            failed.failed_images = max(1, failed.failed_images + 1)
            failed.error_message = (
                f"{_safe_job_error(exc)} 已完成的图片向量和断点均已保留。"
            )
            # Keep the failed image checkpoint visible so operators can identify
            # the exact object while resume still starts from the same item.
            failed.pause_requested_at = None
            failed.paused_at = None
            failed.completed_at = utcnow()
            session.commit()


def _dispatch_image_index_job(
    *,
    job_id: UUID,
    organization_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
) -> None:
    _image_index_executor.submit(
        _run_image_index_job,
        job_id=job_id,
        organization_id=organization_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def start_image_index_job(
    session: Session,
    *,
    context: RequestContext,
    request: ImageIndexJobStartRequest,
) -> ImageIndexJobResponse:
    _require(context.permissions, "product.edit")
    if request.mode == "FULL_REBUILD" and not request.confirm_full_rebuild:
        raise ApplicationError(
            "FULL_REBUILD_CONFIRMATION_REQUIRED",
            "全量重建图片索引需要明确确认。",
        )
    _expire_stale_job(session, tenant_id=context.tenant_id)
    existing = _active_job(session, tenant_id=context.tenant_id)
    if existing is not None:
        return _job_response(existing)
    provider = _provider(session)
    identity = provider.identity
    targets = repository.list_index_target_images(
        session,
        tenant_id=context.tenant_id,
        provider=identity.provider,
        model=identity.model_name,
        version=identity.model_version,
        dimensions=identity.dimensions,
        full_rebuild=request.mode == "FULL_REBUILD",
    )
    now = utcnow()
    job = ImageIndexJobRow(
        tenant_id=context.tenant_id,
        requested_by_membership_id=context.membership_id,
        requested_by_user_id=context.user_id,
        mode=request.mode,
        status="SUCCEEDED" if not targets else "QUEUED",
        total_images=len(targets),
        processed_images=0,
        failed_images=0,
        embeddings=0,
        model_provider=identity.provider,
        model_name=identity.model_name,
        model_version=identity.model_version,
        dimensions=identity.dimensions,
        remaining_image_ids=[str(image_id) for image_id, _ in targets],
        completed_at=now if not targets else None,
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = _active_job(session, tenant_id=context.tenant_id)
        if existing is not None:
            return _job_response(existing)
        raise ApplicationError(
            "IMAGE_INDEX_BUSY",
            "当前商家的图片向量化任务正在执行。",
            kind="conflict",
        ) from exc
    if targets:
        _dispatch_image_index_job(
            job_id=job.id,
            organization_id=context.organization_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
    return _job_response(job)


def pause_image_index_job(
    session: Session,
    *,
    context: RequestContext,
    job_id: UUID,
) -> ImageIndexJobResponse:
    _require(context.permissions, "product.edit")
    job = _managed_job(
        session,
        tenant_id=context.tenant_id,
        job_id=job_id,
        for_update=True,
    )
    if job.status == "PAUSED":
        return _job_response(job)
    if job.status not in {"QUEUED", "RUNNING"}:
        raise ApplicationError(
            "IMAGE_INDEX_JOB_NOT_PAUSABLE",
            "当前图片向量化任务已经结束。",
            kind="conflict",
        )
    now = utcnow()
    job.pause_requested_at = now
    if job.status == "QUEUED":
        job.status = "PAUSED"
        job.paused_at = now
    session.commit()
    return _job_response(job)


def resume_image_index_job(
    session: Session,
    *,
    context: RequestContext,
    job_id: UUID,
) -> ImageIndexJobResponse:
    _require(context.permissions, "product.edit")
    job = _managed_job(
        session,
        tenant_id=context.tenant_id,
        job_id=job_id,
        for_update=True,
    )
    if job.status == "RUNNING" and job.pause_requested_at is not None:
        job.pause_requested_at = None
        session.commit()
        return _job_response(job)
    if job.status not in {"PAUSED", "FAILED"}:
        raise ApplicationError(
            "IMAGE_INDEX_JOB_NOT_RESUMABLE",
            "只有已暂停或中断的图片向量化任务可以继续。",
            kind="conflict",
        )
    existing = _active_job(session, tenant_id=context.tenant_id)
    if existing is not None and existing.id != job.id:
        raise ApplicationError(
            "IMAGE_INDEX_JOB_CONFLICT",
            "当前商家已有另一个图片向量化任务。",
            kind="conflict",
        )
    provider = _provider(session)
    identity = provider.identity
    identity_changed = (
        job.model_provider,
        job.model_name,
        job.model_version,
        job.dimensions,
    ) != (
        identity.provider,
        identity.model_name,
        identity.model_version,
        identity.dimensions,
    )
    if identity_changed:
        targets = repository.list_index_target_images(
            session,
            tenant_id=context.tenant_id,
            provider=identity.provider,
            model=identity.model_name,
            version=identity.model_version,
            dimensions=identity.dimensions,
            full_rebuild=job.mode == "FULL_REBUILD",
        )
        job.processed_images = 0
        job.embeddings = 0
        job.total_images = len(targets)
        job.remaining_image_ids = [str(image_id) for image_id, _ in targets]
        job.model_provider = identity.provider
        job.model_name = identity.model_name
        job.model_version = identity.model_version
        job.dimensions = identity.dimensions
    job.status = "QUEUED"
    job.pause_requested_at = None
    job.paused_at = None
    job.failed_images = 0
    job.error_message = None
    job.current_image_id = None
    job.current_product_name = None
    job.completed_at = None
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "IMAGE_INDEX_JOB_CONFLICT",
            "当前商家已有另一个图片向量化任务。",
            kind="conflict",
        ) from exc
    _dispatch_image_index_job(
        job_id=job.id,
        organization_id=context.organization_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
    )
    return _job_response(job)


def recover_interrupted_image_index_jobs() -> int:
    """Convert unfinished process-owned jobs into resumable checkpoints."""

    recovered = 0
    with SessionLocal() as directory_session:
        dialect = (
            directory_session.bind.dialect.name
            if directory_session.bind is not None
            else "unknown"
        )
        if dialect == "postgresql":
            directory_url = os.getenv("TENANT_DIRECTORY_DATABASE_URL", "").strip()
            tenant_ids: tuple[UUID, ...] = ()
            if directory_url:
                psycopg_url = directory_url.replace(
                    "postgresql+psycopg://",
                    "postgresql://",
                    1,
                )
                try:
                    with psycopg.connect(
                        psycopg_url,
                        connect_timeout=5,
                    ) as connection:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "SELECT id FROM tenants "
                                "WHERE status='active' AND deleted_at IS NULL "
                                "ORDER BY id"
                            )
                            tenant_ids = tuple(
                                UUID(str(row[0])) for row in cursor.fetchall()
                            )
                except psycopg.Error:
                    logger.exception(
                        "image index recovery could not read tenant directory"
                    )
        else:
            tenant_ids = tuple(
                directory_session.scalars(
                    select(ImageIndexJobRow.tenant_id)
                    .where(
                        ImageIndexJobRow.status.in_(("QUEUED", "RUNNING")),
                        ImageIndexJobRow.deleted_at.is_(None),
                    )
                    .distinct()
                ).all()
            )
        directory_session.rollback()
    for tenant_id in tenant_ids:
        try:
            with SessionLocal() as session:
                set_request_context(
                    session,
                    organization_id=_ZERO_IDENTITY,
                    tenant_id=tenant_id,
                    user_id=_ZERO_IDENTITY,
                )
                rows = list(
                    session.scalars(
                        select(ImageIndexJobRow).where(
                            ImageIndexJobRow.tenant_id == tenant_id,
                            ImageIndexJobRow.status.in_(("QUEUED", "RUNNING")),
                            ImageIndexJobRow.deleted_at.is_(None),
                        )
                    ).all()
                )
                now = utcnow()
                for job in rows:
                    job.status = "PAUSED"
                    job.pause_requested_at = None
                    job.paused_at = now
                    job.current_image_id = None
                    job.current_product_name = None
                    job.error_message = "服务重启前的图片向量进度已保存，可继续。"
                    job.completed_at = None
                session.commit()
                recovered += len(rows)
        except Exception:
            logger.exception(
                "image index checkpoint recovery failed for tenant %s",
                tenant_id,
            )
    return recovered
