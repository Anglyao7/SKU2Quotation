import time
from dataclasses import asdict, dataclass
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from ..database import set_request_context
from ..domain.errors import ApplicationError
from ..embedding_management_models import KnowledgeIndexJobRow
from ..identity_models import TenantRow
from ..knowledge_embedding_models import EmbeddingRow
from ..knowledge_embedding_schemas import (
    EmbeddingSettingsResponse,
    EmbeddingSettingsUpdateRequest,
)
from ..model_mixins import utcnow
from ..product_supplier_models import ProductRow
from ..services.auth.dependencies import RequestContext
from ..services.embedding import EmbeddingProviderError
from ..services.embedding_configuration import (
    embedding_configuration_snapshot,
    save_managed_embedding_settings,
)
from ..support_ai_models import (
    SupportAIIngestionJobRow,
    SupportAIKnowledgeChunkRow,
)


_DATABASE_SAVE_ATTEMPTS = 3
_ACTIVE_JOB_WINDOW = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class _EmbeddingInvalidation:
    model_changed: bool = False
    cleared_product_embeddings: int = 0
    cleared_file_embeddings: int = 0
    invalidated_products: int = 0


def _retryable_database_error(exc: DBAPIError) -> bool:
    """Recognize short-lived database failures without exposing driver details."""

    original = exc.orig
    sqlstate = str(
        getattr(original, "sqlstate", "")
        or getattr(original, "pgcode", "")
    ).strip()
    if sqlstate in {"40001", "40P01", "55P03", "57014", "57P01"}:
        return True
    message = str(original).casefold()
    return any(
        marker in message
        for marker in (
            "database is locked",
            "database table is locked",
            "deadlock detected",
            "could not serialize access",
            "lock timeout",
            "connection reset",
            "connection was closed",
            "server closed the connection",
        )
    )


def _normalized_model_identity(
    *,
    provider: str,
    base_url: str | None,
    model_name: str,
    dimensions: int,
) -> tuple[str, str, str, int]:
    return (
        provider.strip().casefold(),
        (base_url or "").strip().rstrip("/"),
        model_name.strip(),
        dimensions,
    )


def _row_count(result: object) -> int:
    value = getattr(result, "rowcount", 0)
    return int(value) if isinstance(value, int) and value > 0 else 0


def _clear_embeddings_after_model_change(
    session: Session,
    *,
    context: RequestContext,
) -> _EmbeddingInvalidation:
    tenants = list(
        session.execute(
            select(TenantRow.id, TenantRow.organization_id).where(
                TenantRow.deleted_at.is_(None)
            )
        ).all()
    )
    recent = utcnow() - _ACTIVE_JOB_WINDOW
    try:
        for tenant_id, organization_id in tenants:
            set_request_context(
                session,
                organization_id=organization_id,
                tenant_id=tenant_id,
                user_id=context.user_id,
            )
            active_index_job = session.scalar(
                select(KnowledgeIndexJobRow.id)
                .where(
                    KnowledgeIndexJobRow.tenant_id == tenant_id,
                    KnowledgeIndexJobRow.status.in_(("QUEUED", "RUNNING")),
                    KnowledgeIndexJobRow.updated_at >= recent,
                    KnowledgeIndexJobRow.deleted_at.is_(None),
                )
                .limit(1)
            )
            active_file_job = session.scalar(
                select(SupportAIIngestionJobRow.id)
                .where(
                    SupportAIIngestionJobRow.tenant_id == tenant_id,
                    SupportAIIngestionJobRow.status.in_(("QUEUED", "RUNNING")),
                    SupportAIIngestionJobRow.updated_at >= recent,
                    SupportAIIngestionJobRow.deleted_at.is_(None),
                )
                .limit(1)
            )
            if active_index_job is not None or active_file_job is not None:
                raise ApplicationError(
                    "EMBEDDING_MODEL_CHANGE_BUSY",
                    "当前仍有向量化任务运行，请等待任务完成后再更换模型。",
                    kind="conflict",
                )

        cleared_product_embeddings = 0
        cleared_file_embeddings = 0
        invalidated_products = 0
        for tenant_id, organization_id in tenants:
            set_request_context(
                session,
                organization_id=organization_id,
                tenant_id=tenant_id,
                user_id=context.user_id,
            )
            cleared_product_embeddings += _row_count(
                session.execute(
                    delete(EmbeddingRow).where(EmbeddingRow.tenant_id == tenant_id)
                )
            )
            cleared_file_embeddings += _row_count(
                session.execute(
                    update(SupportAIKnowledgeChunkRow)
                    .where(
                        SupportAIKnowledgeChunkRow.tenant_id == tenant_id,
                        SupportAIKnowledgeChunkRow.embedding.is_not(None),
                    )
                    .values(
                        embedding=None,
                        embedding_provider=None,
                        embedding_model=None,
                        embedding_version=None,
                        embedding_dimensions=None,
                        updated_at=utcnow(),
                    )
                )
            )
            invalidated_products += _row_count(
                session.execute(
                    update(ProductRow)
                    .where(
                        ProductRow.tenant_id == tenant_id,
                        ProductRow.search_document_version != 0,
                    )
                    .values(search_document_version=0)
                )
            )
        session.flush()
        return _EmbeddingInvalidation(
            model_changed=True,
            cleared_product_embeddings=cleared_product_embeddings,
            cleared_file_embeddings=cleared_file_embeddings,
            invalidated_products=invalidated_products,
        )
    finally:
        set_request_context(
            session,
            organization_id=context.organization_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )


def _require_platform_admin(context: RequestContext) -> None:
    if not context.is_platform_admin:
        raise ApplicationError(
            "PLATFORM_ADMIN_REQUIRED",
            "Platform administrator access is required.",
            kind="forbidden",
        )


def get_settings(
    session: Session,
    *,
    context: RequestContext,
) -> EmbeddingSettingsResponse:
    _require_platform_admin(context)
    try:
        snapshot = embedding_configuration_snapshot(session)
    except (ValueError, EmbeddingProviderError) as exc:
        raise ApplicationError(
            "EMBEDDING_CONFIGURATION_INVALID",
            str(exc),
        ) from exc
    return EmbeddingSettingsResponse(**asdict(snapshot))


def update_settings(
    session: Session,
    *,
    context: RequestContext,
    request: EmbeddingSettingsUpdateRequest,
) -> EmbeddingSettingsResponse:
    _require_platform_admin(context)
    for attempt in range(_DATABASE_SAVE_ATTEMPTS):
        try:
            previous = embedding_configuration_snapshot(session)
            settings = save_managed_embedding_settings(
                session,
                base_url=request.base_url,
                model_name=request.model_name,
                dimensions=request.dimensions,
                timeout_seconds=request.timeout_seconds,
                max_retry_count=request.max_retry_count,
                api_key=(
                    request.api_key.get_secret_value()
                    if request.api_key is not None
                    else None
                ),
                updated_by_user_id=context.user_id,
            )
            model_changed = _normalized_model_identity(
                provider=previous.provider,
                base_url=previous.base_url,
                model_name=previous.model_name,
                dimensions=previous.dimensions,
            ) != _normalized_model_identity(
                provider=settings.provider,
                base_url=settings.base_url,
                model_name=settings.model_name,
                dimensions=settings.dimensions,
            )
            invalidation = (
                _clear_embeddings_after_model_change(
                    session,
                    context=context,
                )
                if model_changed
                else _EmbeddingInvalidation()
            )
            session.commit()
            snapshot = embedding_configuration_snapshot(session)
            return EmbeddingSettingsResponse(
                **asdict(snapshot),
                **asdict(invalidation),
            )
        except ApplicationError:
            session.rollback()
            raise
        except (ValueError, EmbeddingProviderError) as exc:
            session.rollback()
            raise ApplicationError(
                "EMBEDDING_CONFIGURATION_INVALID",
                str(exc),
            ) from exc
        except DBAPIError as exc:
            session.rollback()
            if (
                _retryable_database_error(exc)
                and attempt + 1 < _DATABASE_SAVE_ATTEMPTS
            ):
                time.sleep(0.12 * (2**attempt))
                continue
            raise ApplicationError(
                "EMBEDDING_CONFIGURATION_SAVE_UNAVAILABLE",
                "Embedding 配置暂时无法保存，请稍后重试。",
                kind="unavailable",
            ) from exc
    raise AssertionError("unreachable")
