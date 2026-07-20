from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai_data_models import AISourceEvidenceRow
from ..identity_models import MembershipRow
from ..product_intelligence_models import (
    ProductCandidateDecisionRow,
    ProductFieldCandidateRow,
)


def list_candidates_with_evidence(
    session: Session,
    *,
    tenant_id: UUID,
    task_id: UUID,
) -> list[tuple[ProductFieldCandidateRow, AISourceEvidenceRow]]:
    return list(
        session.execute(
            select(ProductFieldCandidateRow, AISourceEvidenceRow)
            .join(
                AISourceEvidenceRow,
                (
                    AISourceEvidenceRow.tenant_id
                    == ProductFieldCandidateRow.tenant_id
                )
                & (
                    AISourceEvidenceRow.id
                    == ProductFieldCandidateRow.source_evidence_id
                ),
            )
            .where(
                ProductFieldCandidateRow.tenant_id == tenant_id,
                ProductFieldCandidateRow.ai_task_id == task_id,
            )
            .order_by(
                ProductFieldCandidateRow.candidate_index,
                ProductFieldCandidateRow.field_key,
            )
        ).all()
    )


def latest_decisions_by_group(
    session: Session,
    *,
    tenant_id: UUID,
    task_id: UUID,
) -> dict[str, ProductCandidateDecisionRow]:
    rows = session.scalars(
        select(ProductCandidateDecisionRow)
        .where(
            ProductCandidateDecisionRow.tenant_id == tenant_id,
            ProductCandidateDecisionRow.ai_task_id == task_id,
        )
        .order_by(
            ProductCandidateDecisionRow.created_at.desc(),
            ProductCandidateDecisionRow.id.desc(),
        )
    ).all()
    latest: dict[str, ProductCandidateDecisionRow] = {}
    for row in rows:
        latest.setdefault(row.candidate_group_key, row)
    return latest


def active_membership_id(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
) -> UUID | None:
    return session.scalar(
        select(MembershipRow.id).where(
            MembershipRow.tenant_id == tenant_id,
            MembershipRow.user_id == user_id,
            MembershipRow.status == "active",
        )
    )
