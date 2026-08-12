from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..constants import DEFAULT_MEMBERSHIP_ID, DEFAULT_OWNER_USER_ID, DEFAULT_TENANT_ID
from ..domain.errors import ApplicationError
from ..models import (
    ProductCandidateApproveRequest,
    ProductCandidateApproveResponse,
    ProductCandidateDecisionSummary,
    ProductCandidateEvidence,
    ProductCandidateRejectRequest,
    ProductCandidateRejectResponse,
    ProductFieldCandidate,
)
from ..repositories.product_intelligence_repository import (
    active_membership_id,
    latest_decisions_by_group,
    list_candidates_with_evidence,
)
from ..runtime_config import inline_database_outbox_enabled
from ..services.product_intelligence.adoption import (
    ProductAdoptionError,
    approve_candidate_group,
    dispatch_product_committed_event,
    reject_candidate_group,
)
from ..services.rbac import has_permission
from ..services.catalog_write_guard import (
    lock_catalog_write,
    release_rollback_ownership,
)


def _membership_id(session: Session, *, tenant_id: UUID, user_id: UUID) -> UUID:
    if tenant_id == DEFAULT_TENANT_ID and user_id == DEFAULT_OWNER_USER_ID:
        return DEFAULT_MEMBERSHIP_ID
    membership_id = active_membership_id(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    if membership_id is None:
        raise ApplicationError(
            "REVIEWER_NOT_ACTIVE",
            "Active tenant membership is required.",
            kind="forbidden",
        )
    return membership_id


def _require_permission(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    permission_code: str,
) -> None:
    if not has_permission(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        permission_code=permission_code,
    ):
        raise ApplicationError(
            "PERMISSION_REQUIRED",
            f"Permission required: {permission_code}",
            kind="forbidden",
        )


def _adoption_error(exc: ProductAdoptionError) -> ApplicationError:
    if exc.code in {"CANDIDATE_GROUP_NOT_FOUND", "TARGET_PRODUCT_NOT_FOUND"}:
        kind = "not_found"
    elif exc.code in {
        "CANDIDATE_GROUP_ALREADY_APPLIED",
        "PRODUCT_VERSION_CONFLICT",
        "IDEMPOTENCY_KEY_REUSED",
        "ADOPTION_EVENT_MISSING",
    }:
        kind = "conflict"
    elif exc.code == "REVIEWER_NOT_ACTIVE":
        kind = "forbidden"
    else:
        kind = "invalid"
    return ApplicationError(exc.code, exc.safe_message, kind=kind)


def list_candidates(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    task_id: UUID,
) -> list[ProductFieldCandidate]:
    _require_permission(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        permission_code="product.review",
    )
    rows = list_candidates_with_evidence(
        session,
        tenant_id=tenant_id,
        task_id=task_id,
    )
    latest_by_group = latest_decisions_by_group(
        session,
        tenant_id=tenant_id,
        task_id=task_id,
    )
    return [
        ProductFieldCandidate(
            id=str(candidate.id),
            task_id=str(candidate.ai_task_id),
            candidate_group_key=candidate.candidate_group_key,
            candidate_index=candidate.candidate_index,
            field_key=candidate.field_key,
            raw_value=candidate.raw_value,
            normalized_value=candidate.normalized_value,
            normalized_unit=candidate.normalized_unit,
            confidence=candidate.confidence,
            validation_status=candidate.validation_status,
            review_status=candidate.review_status,
            warnings=candidate.warnings,
            normalization_rule_version=candidate.normalization_rule_version,
            normalization_trace=candidate.normalization_trace,
            evidence=ProductCandidateEvidence(
                source_file_id=evidence.source_file_id,
                location=evidence.location,
                raw_value_hash=evidence.raw_value_hash,
            ),
            latest_decision=(
                ProductCandidateDecisionSummary(
                    id=str(latest_by_group[candidate.candidate_group_key].id),
                    action=latest_by_group[candidate.candidate_group_key].action,
                    status=latest_by_group[candidate.candidate_group_key].status,
                    product_id=(
                        str(latest_by_group[candidate.candidate_group_key].product_id)
                        if latest_by_group[candidate.candidate_group_key].product_id
                        else None
                    ),
                    applied_product_version=latest_by_group[
                        candidate.candidate_group_key
                    ].applied_product_version,
                    reviewed_by_membership_id=str(
                        latest_by_group[
                            candidate.candidate_group_key
                        ].reviewed_by_membership_id
                    ),
                    reviewed_at=latest_by_group[
                        candidate.candidate_group_key
                    ].reviewed_at.isoformat(),
                )
                if candidate.candidate_group_key in latest_by_group
                else None
            ),
        )
        for candidate, evidence in rows
    ]


def approve_candidate(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    task_id: UUID,
    candidate_group_key: str,
    request: ProductCandidateApproveRequest,
) -> ProductCandidateApproveResponse:
    _require_permission(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        permission_code="product.review",
    )
    _require_permission(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        permission_code="product.edit" if request.target_product_id else "product.create",
    )
    if request.target_product_id is not None:
        lock_catalog_write(session, tenant_id=tenant_id)
        release_rollback_ownership(
            session,
            tenant_id=tenant_id,
            product_ids=[request.target_product_id],
        )
    try:
        result = approve_candidate_group(
            session,
            tenant_id=tenant_id,
            task_id=task_id,
            candidate_group_key=candidate_group_key,
            reviewer_membership_id=_membership_id(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
            ),
            idempotency_key=request.idempotency_key,
            confirmed_values=request.confirmed_values,
            activate=request.activate,
            target_product_id=request.target_product_id,
            expected_product_version=request.expected_product_version,
            product_code=request.product_code,
            change_reason=request.change_reason,
        )
        session.commit()
        outbox_status = result.outbox_status
        if inline_database_outbox_enabled():
            dispatch = dispatch_product_committed_event(
                session,
                tenant_id=tenant_id,
                event_id=result.outbox_event_id,
            )
            session.commit()
            outbox_status = dispatch.status
    except ProductAdoptionError as exc:
        session.rollback()
        raise _adoption_error(exc) from exc
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "PRODUCT_ADOPTION_CONFLICT",
            "Product adoption conflicted with a concurrent or duplicate write.",
            kind="conflict",
        ) from exc
    return ProductCandidateApproveResponse(
        decision_id=str(result.decision_id),
        product_id=str(result.product_id),
        product_version=result.product_version,
        outbox_event_id=str(result.outbox_event_id),
        outbox_status=outbox_status,
        idempotent=result.idempotent,
    )


def reject_candidate(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    task_id: UUID,
    candidate_group_key: str,
    request: ProductCandidateRejectRequest,
) -> ProductCandidateRejectResponse:
    _require_permission(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        permission_code="product.review",
    )
    try:
        result = reject_candidate_group(
            session,
            tenant_id=tenant_id,
            task_id=task_id,
            candidate_group_key=candidate_group_key,
            reviewer_membership_id=_membership_id(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
            ),
            idempotency_key=request.idempotency_key,
            reason=request.reason,
        )
        session.commit()
    except ProductAdoptionError as exc:
        session.rollback()
        raise _adoption_error(exc) from exc
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "PRODUCT_REVIEW_CONFLICT",
            "Product review conflicted with a concurrent or duplicate write.",
            kind="conflict",
        ) from exc
    return ProductCandidateRejectResponse(
        decision_id=str(result.decision_id),
        status=result.status,
        idempotent=result.idempotent,
    )
