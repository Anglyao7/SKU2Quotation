from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from typing import Any, Iterator
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import set_request_context
from ..domain.errors import ApplicationError
from ..identity_models import TenantRow
from ..model_mixins import mark_deleted, utcnow
from ..services.auth.dependencies import RequestContext
from ..support_ai_models import (
    SupportAIAgentRow,
    SupportAIKnowledgeBaseRow,
    SupportAISettingsRow,
    SupportAITrainingCaseRow,
    SupportAITrainingRuleRow,
    SupportAITrainingVersionRow,
)
from ..support_ai_schemas import (
    SupportAITrainingCaseResponse,
    SupportAITrainingCaseWrite,
    SupportAITrainingCopyRequest,
    SupportAITrainingOverviewResponse,
    SupportAITrainingPackage,
    SupportAITrainingPreviewResponse,
    SupportAITrainingPublishRequest,
    SupportAITrainingRuleResponse,
    SupportAITrainingRuleWrite,
    SupportAITrainingVersionResponse,
)


TRAINING_SCHEMA_VERSION = "support-ai-training/v1"
TRAINING_BOUNDARY = [
    "Training cases and rules teach response behavior; they are not merchant-fact evidence.",
    "Product facts such as price, MOQ, stock, specification and product code must come from current approved evidence.",
    "A published example may be imitated structurally, but its facts, numbers, citations and identifiers must never be copied into another answer.",
    "Imported or manually edited material remains draft until a platform administrator approves it through the one-click release flow.",
]
SUPPORTED_SCOPES = {
    "QUESTION_ANSWERING",
    "PRODUCT_RECOMMENDATION",
    "GREETING",
    "CLARIFICATION",
    "HANDOFF",
    "MULTILINGUAL",
}
TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]{1,}", re.IGNORECASE)


def _require_platform_admin(context: RequestContext) -> None:
    if not context.is_platform_admin:
        raise ApplicationError(
            "PLATFORM_ADMIN_REQUIRED",
            "Platform administrator access is required.",
            kind="forbidden",
        )


def _agent(session: Session, agent_id: UUID) -> SupportAIAgentRow:
    row = session.scalar(
        select(SupportAIAgentRow).where(SupportAIAgentRow.id == agent_id)
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_AI_AGENT_NOT_FOUND", "智能体不存在。", kind="not_found"
        )
    return row


def _tenant(session: Session, tenant_id: UUID) -> TenantRow:
    row = session.scalar(
        select(TenantRow).where(
            TenantRow.id == tenant_id,
            TenantRow.deleted_at.is_(None),
        )
    )
    if row is None:
        raise ApplicationError("TENANT_NOT_FOUND", "店铺不存在。", kind="not_found")
    return row


def _knowledge_base(
    session: Session,
    *,
    agent_id: UUID,
    knowledge_base_id: UUID | None,
) -> SupportAIKnowledgeBaseRow | None:
    if knowledge_base_id is None:
        return None
    row = session.scalar(
        select(SupportAIKnowledgeBaseRow).where(
            SupportAIKnowledgeBaseRow.id == knowledge_base_id,
            SupportAIKnowledgeBaseRow.agent_id == agent_id,
            SupportAIKnowledgeBaseRow.deleted_at.is_(None),
        )
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_AI_KNOWLEDGE_BASE_NOT_FOUND",
            "知识库不存在或未绑定到该智能体。",
            kind="not_found",
        )
    return row


@contextmanager
def _tenant_scope(
    session: Session,
    *,
    context: RequestContext,
    tenant: TenantRow,
) -> Iterator[None]:
    set_request_context(
        session,
        organization_id=tenant.organization_id,
        tenant_id=tenant.id,
        user_id=context.user_id,
    )
    try:
        yield
    finally:
        set_request_context(
            session,
            organization_id=context.organization_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )


def _case_response(row: SupportAITrainingCaseRow) -> SupportAITrainingCaseResponse:
    return SupportAITrainingCaseResponse(
        id=row.id,
        agent_id=row.agent_id,
        knowledge_base_id=row.knowledge_base_id,
        external_id=row.external_id,
        source_tenant_id=row.source_tenant_id,
        title=row.title,
        language=row.language,
        customer_message=row.customer_message,
        ideal_response=row.ideal_response,
        response_action=row.response_action,
        grounding_mode=row.grounding_mode,
        behavior_notes=row.behavior_notes,
        required_evidence_types=list(row.required_evidence_types or []),
        tags=list(row.tags or []),
        forbidden_patterns=list(row.forbidden_patterns or []),
        source_type=row.source_type,
        status=row.status,
        sort_order=row.sort_order,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _rule_response(row: SupportAITrainingRuleRow) -> SupportAITrainingRuleResponse:
    valid_case_ids: list[UUID] = []
    for value in row.source_case_ids or []:
        try:
            valid_case_ids.append(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return SupportAITrainingRuleResponse(
        id=row.id,
        agent_id=row.agent_id,
        knowledge_base_id=row.knowledge_base_id,
        rule_key=row.rule_key,
        title=row.title,
        instruction=row.instruction,
        scopes=list(row.scopes or []),
        source_case_ids=valid_case_ids,
        priority=row.priority,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _version_response(
    row: SupportAITrainingVersionRow,
) -> SupportAITrainingVersionResponse:
    return SupportAITrainingVersionResponse(
        id=row.id,
        agent_id=row.agent_id,
        knowledge_base_id=row.knowledge_base_id,
        version_number=row.version_number,
        status=row.status,
        package_hash=row.package_hash,
        compiled_prompt=row.compiled_prompt,
        case_count=len(row.case_snapshot or []),
        rule_count=len(row.rule_snapshot or []),
        release_notes=row.release_notes,
        published_at=row.published_at,
        activated_at=row.activated_at,
        retired_at=row.retired_at,
    )


def _cases(
    session: Session,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
) -> list[SupportAITrainingCaseRow]:
    scope = SupportAITrainingCaseRow.knowledge_base_id.is_(None)
    if knowledge_base_id is not None:
        scope = scope | (SupportAITrainingCaseRow.knowledge_base_id == knowledge_base_id)
    return list(
        session.scalars(
            select(SupportAITrainingCaseRow)
            .where(SupportAITrainingCaseRow.agent_id == agent_id, scope)
            .order_by(
                SupportAITrainingCaseRow.sort_order,
                SupportAITrainingCaseRow.updated_at.desc(),
            )
        ).all()
    )


def _rules(
    session: Session,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
) -> list[SupportAITrainingRuleRow]:
    scope = SupportAITrainingRuleRow.knowledge_base_id.is_(None)
    if knowledge_base_id is not None:
        scope = scope | (SupportAITrainingRuleRow.knowledge_base_id == knowledge_base_id)
    return list(
        session.scalars(
            select(SupportAITrainingRuleRow)
            .where(SupportAITrainingRuleRow.agent_id == agent_id, scope)
            .order_by(
                SupportAITrainingRuleRow.priority.desc(),
                SupportAITrainingRuleRow.updated_at.desc(),
            )
        ).all()
    )


def _versions(
    session: Session,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
) -> list[SupportAITrainingVersionRow]:
    scope = SupportAITrainingVersionRow.knowledge_base_id.is_(None)
    if knowledge_base_id is not None:
        scope = scope | (SupportAITrainingVersionRow.knowledge_base_id == knowledge_base_id)
    return list(
        session.scalars(
            select(SupportAITrainingVersionRow)
            .where(SupportAITrainingVersionRow.agent_id == agent_id, scope)
            .order_by(SupportAITrainingVersionRow.version_number.desc())
        ).all()
    )


def get_training_overview(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
) -> SupportAITrainingOverviewResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    cases = _cases(session, agent_id, knowledge_base_id)
    rules = _rules(session, agent_id, knowledge_base_id)
    versions = _versions(session, agent_id, knowledge_base_id)
    active = next(
        (
            row
            for row in versions
            if row.status == "PUBLISHED"
            and (
                knowledge_base_id is not None
                and row.knowledge_base_id == knowledge_base_id
            )
        ),
        None,
    )
    if active is None:
        active = next(
            (
                row
                for row in versions
                if row.status == "PUBLISHED" and row.knowledge_base_id is None
            ),
            None,
        )
    return SupportAITrainingOverviewResponse(
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        cases=[_case_response(row) for row in cases],
        rules=[_rule_response(row) for row in rules],
        versions=[_version_response(row) for row in versions],
        active_version_id=active.id if active else None,
        active_version_number=active.version_number if active else None,
        draft_case_count=sum(row.status == "DRAFT" for row in cases),
        approved_case_count=sum(row.status == "APPROVED" for row in cases),
        draft_rule_count=sum(row.status == "DRAFT" for row in rules),
        approved_rule_count=sum(row.status == "APPROVED" for row in rules),
    )


def _unique_external_id(
    session: Session,
    *,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
    preferred: str | None,
    prefix: str,
) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", preferred or "").strip("-.")
    base = (normalized or f"{prefix}-{uuid4().hex[:12]}")[:110]
    candidate = base
    knowledge_base_scope = (
        SupportAITrainingCaseRow.knowledge_base_id == knowledge_base_id
        if knowledge_base_id is not None
        else SupportAITrainingCaseRow.knowledge_base_id.is_(None)
    )
    for suffix in range(1, 1000):
        exists = session.scalar(
            select(SupportAITrainingCaseRow.id)
            .execution_options(include_deleted=True)
            .where(
                SupportAITrainingCaseRow.agent_id == agent_id,
                knowledge_base_scope,
                SupportAITrainingCaseRow.external_id == candidate,
            )
        )
        if exists is None:
            return candidate
        candidate = f"{base[:105]}-{suffix}"
    return f"{prefix}-{uuid4().hex}"


def _unique_rule_key(
    session: Session,
    *,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
    preferred: str | None,
) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", preferred or "").strip("-.")
    base = (normalized or f"rule-{uuid4().hex[:12]}")[:110]
    candidate = base
    knowledge_base_scope = (
        SupportAITrainingRuleRow.knowledge_base_id == knowledge_base_id
        if knowledge_base_id is not None
        else SupportAITrainingRuleRow.knowledge_base_id.is_(None)
    )
    for suffix in range(1, 1000):
        exists = session.scalar(
            select(SupportAITrainingRuleRow.id)
            .execution_options(include_deleted=True)
            .where(
                SupportAITrainingRuleRow.agent_id == agent_id,
                knowledge_base_scope,
                SupportAITrainingRuleRow.rule_key == candidate,
            )
        )
        if exists is None:
            return candidate
        candidate = f"{base[:105]}-{suffix}"
    return f"rule-{uuid4().hex}"


def _apply_case(
    row: SupportAITrainingCaseRow,
    request: SupportAITrainingCaseWrite,
    *,
    user_id: UUID,
) -> None:
    row.source_tenant_id = request.source_tenant_id
    row.title = request.title
    row.language = request.language
    row.customer_message = request.customer_message
    row.ideal_response = request.ideal_response
    row.response_action = request.response_action
    row.grounding_mode = request.grounding_mode
    row.behavior_notes = request.behavior_notes
    row.required_evidence_types = list(request.required_evidence_types)
    row.tags = list(request.tags)
    row.forbidden_patterns = list(request.forbidden_patterns)
    row.source_type = request.source_type
    row.status = request.status
    row.sort_order = request.sort_order
    row.updated_by_user_id = user_id
    row.updated_at = utcnow()


def create_training_case(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
    request: SupportAITrainingCaseWrite,
) -> SupportAITrainingCaseResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    _validate_case_source_tenant(
        session,
        context=context,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        source_tenant_id=request.source_tenant_id,
    )
    row = SupportAITrainingCaseRow(
        id=uuid4(),
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        external_id=_unique_external_id(
            session,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            preferred=request.external_id,
            prefix="manual",
        ),
        title=request.title,
        language=request.language,
        customer_message=request.customer_message,
        ideal_response=request.ideal_response,
        created_by_user_id=context.user_id,
        updated_by_user_id=context.user_id,
    )
    _apply_case(row, request, user_id=context.user_id)
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_CASE_CONFLICT", "训练案例保存冲突。", kind="conflict"
        ) from exc
    return _case_response(row)


def update_training_case(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    case_id: UUID,
    knowledge_base_id: UUID | None = None,
    request: SupportAITrainingCaseWrite,
) -> SupportAITrainingCaseResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    row = session.scalar(
        select(SupportAITrainingCaseRow).where(
            SupportAITrainingCaseRow.id == case_id,
            SupportAITrainingCaseRow.agent_id == agent_id,
            (
                SupportAITrainingCaseRow.knowledge_base_id == knowledge_base_id
                if knowledge_base_id is not None
                else SupportAITrainingCaseRow.knowledge_base_id.is_(None)
            ),
        )
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_CASE_NOT_FOUND", "训练案例不存在。", kind="not_found"
        )
    _validate_case_source_tenant(
        session,
        context=context,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        source_tenant_id=request.source_tenant_id,
        existing_source_tenant_id=row.source_tenant_id,
    )
    _apply_case(row, request, user_id=context.user_id)
    session.commit()
    return _case_response(row)


def delete_training_case(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    case_id: UUID,
    knowledge_base_id: UUID | None = None,
) -> None:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    row = session.scalar(
        select(SupportAITrainingCaseRow).where(
            SupportAITrainingCaseRow.id == case_id,
            SupportAITrainingCaseRow.agent_id == agent_id,
            (
                SupportAITrainingCaseRow.knowledge_base_id == knowledge_base_id
                if knowledge_base_id is not None
                else SupportAITrainingCaseRow.knowledge_base_id.is_(None)
            ),
        )
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_CASE_NOT_FOUND", "训练案例不存在。", kind="not_found"
        )
    mark_deleted(row)
    row.updated_by_user_id = context.user_id
    session.commit()


def _apply_rule(
    row: SupportAITrainingRuleRow,
    request: SupportAITrainingRuleWrite,
    *,
    user_id: UUID,
) -> None:
    row.title = request.title
    row.instruction = request.instruction
    row.scopes = [scope for scope in request.scopes if scope in SUPPORTED_SCOPES]
    row.source_case_ids = [str(case_id) for case_id in request.source_case_ids]
    row.priority = request.priority
    row.status = request.status
    row.updated_by_user_id = user_id
    row.updated_at = utcnow()


def create_training_rule(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
    request: SupportAITrainingRuleWrite,
) -> SupportAITrainingRuleResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    row = SupportAITrainingRuleRow(
        id=uuid4(),
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        rule_key=_unique_rule_key(
            session,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            preferred=request.rule_key,
        ),
        title=request.title,
        instruction=request.instruction,
        created_by_user_id=context.user_id,
        updated_by_user_id=context.user_id,
    )
    _apply_rule(row, request, user_id=context.user_id)
    session.add(row)
    session.commit()
    return _rule_response(row)


def update_training_rule(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    rule_id: UUID,
    knowledge_base_id: UUID | None = None,
    request: SupportAITrainingRuleWrite,
) -> SupportAITrainingRuleResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    row = session.scalar(
        select(SupportAITrainingRuleRow).where(
            SupportAITrainingRuleRow.id == rule_id,
            SupportAITrainingRuleRow.agent_id == agent_id,
            (
                SupportAITrainingRuleRow.knowledge_base_id == knowledge_base_id
                if knowledge_base_id is not None
                else SupportAITrainingRuleRow.knowledge_base_id.is_(None)
            ),
        )
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_RULE_NOT_FOUND", "训练规则不存在。", kind="not_found"
        )
    _apply_rule(row, request, user_id=context.user_id)
    session.commit()
    return _rule_response(row)


def delete_training_rule(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    rule_id: UUID,
    knowledge_base_id: UUID | None = None,
) -> None:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    row = session.scalar(
        select(SupportAITrainingRuleRow).where(
            SupportAITrainingRuleRow.id == rule_id,
            SupportAITrainingRuleRow.agent_id == agent_id,
            (
                SupportAITrainingRuleRow.knowledge_base_id == knowledge_base_id
                if knowledge_base_id is not None
                else SupportAITrainingRuleRow.knowledge_base_id.is_(None)
            ),
        )
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_RULE_NOT_FOUND", "训练规则不存在。", kind="not_found"
        )
    mark_deleted(row)
    row.updated_by_user_id = context.user_id
    session.commit()


def _bound_tenant_ids(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
) -> list[UUID]:
    knowledge_base = _knowledge_base(
        session,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )
    if knowledge_base is not None:
        return [knowledge_base.tenant_id]
    result: list[UUID] = []
    tenants = session.scalars(
        select(TenantRow).where(
            TenantRow.deleted_at.is_(None),
            TenantRow.status != "archived",
        )
    ).all()
    for tenant in tenants:
        with _tenant_scope(session, context=context, tenant=tenant):
            settings = session.get(SupportAISettingsRow, tenant.id)
            if settings is not None and settings.agent_id == agent_id:
                result.append(tenant.id)
    return sorted(result, key=str)


def _validate_case_source_tenant(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
    source_tenant_id: UUID | None,
    existing_source_tenant_id: UUID | None = None,
) -> None:
    if source_tenant_id is None or source_tenant_id == existing_source_tenant_id:
        return
    if source_tenant_id not in _bound_tenant_ids(
        session,
        context=context,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    ):
        raise ApplicationError(
            "SUPPORT_AI_AGENT_STORE_NOT_BOUND",
            "案例来源店铺未绑定到该智能体。",
            kind="conflict",
        )


def _case_snapshot(row: SupportAITrainingCaseRow) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "external_id": row.external_id,
        "title": row.title,
        "language": row.language,
        "customer_message": row.customer_message,
        "ideal_response": row.ideal_response,
        "response_action": row.response_action,
        "grounding_mode": row.grounding_mode,
        "behavior_notes": row.behavior_notes,
        "required_evidence_types": list(row.required_evidence_types or []),
        "tags": list(row.tags or []),
        "forbidden_patterns": list(row.forbidden_patterns or []),
    }


def _rule_snapshot(row: SupportAITrainingRuleRow) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "rule_key": row.rule_key,
        "title": row.title,
        "instruction": row.instruction,
        "scopes": list(row.scopes or []),
        "source_case_ids": list(row.source_case_ids or []),
        "priority": row.priority,
    }


def _compiled_package(
    session: Session,
    *,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]]:
    approved_cases = [
        row
        for row in _cases(session, agent_id, knowledge_base_id)
        if row.status == "APPROVED"
    ]
    approved_rules = [
        row
        for row in _rules(session, agent_id, knowledge_base_id)
        if row.status == "APPROVED"
    ]
    case_snapshot = [_case_snapshot(row) for row in approved_cases]
    rule_snapshot = [_rule_snapshot(row) for row in approved_rules]
    lines = [
        "Human-reviewed behavior training is active.",
        "Mandatory boundary: training content is never factual evidence. Resolve every merchant-specific fact from the current approved evidence supplied with the visitor question.",
        "Do not copy product names, identifiers, prices, MOQ, specifications, links or citation numbers from training examples unless the same fact appears in current approved evidence.",
        "Apply these reviewed reusable rules when their scope matches:",
    ]
    if approved_rules:
        for index, rule in enumerate(approved_rules, start=1):
            scopes = ", ".join(rule.scopes or []) or "ALL"
            lines.append(
                f"{index}. [{scopes}] {rule.title}: {rule.instruction.strip()}"
            )
    else:
        lines.append("1. No additional reusable rules are currently approved.")
    compiled_prompt = "\n".join(lines)[:24000]
    canonical = json.dumps(
        {
            "schema_version": TRAINING_SCHEMA_VERSION,
            "boundary": TRAINING_BOUNDARY,
            "compiled_prompt": compiled_prompt,
            "cases": case_snapshot,
            "rules": rule_snapshot,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    package_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return compiled_prompt, package_hash, case_snapshot, rule_snapshot


def preview_training_package(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
) -> SupportAITrainingPreviewResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    prompt, package_hash, cases, rules = _compiled_package(
        session, agent_id=agent_id, knowledge_base_id=knowledge_base_id
    )
    return SupportAITrainingPreviewResponse(
        compiled_prompt=prompt,
        package_hash=package_hash,
        approved_case_count=len(cases),
        approved_rule_count=len(rules),
    )


def _activate_version(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    knowledge_base_id: UUID | None,
    version: SupportAITrainingVersionRow,
    user_id: UUID,
) -> None:
    now = utcnow()
    for row in _versions(session, agent_id, knowledge_base_id):
        if knowledge_base_id is not None and row.knowledge_base_id != knowledge_base_id:
            continue
        if row.id != version.id and row.status == "PUBLISHED":
            row.status = "RETIRED"
            row.retired_at = now
    session.flush()
    version.status = "PUBLISHED"
    version.activated_at = now
    version.retired_at = None
    session.flush()
    for tenant_id in _bound_tenant_ids(
        session,
        context=context,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    ):
        tenant = _tenant(session, tenant_id)
        with _tenant_scope(session, context=context, tenant=tenant):
            settings = session.get(SupportAISettingsRow, tenant.id)
            if settings is None or settings.agent_id != agent_id:
                continue
            settings.training_version_id = version.id
            settings.training_prompt = version.compiled_prompt
            settings.training_package_hash = version.package_hash
            settings.training_examples = list(version.case_snapshot or [])
            settings.prompt_version += 1
            settings.updated_by_user_id = user_id
            settings.updated_at = now
            session.flush()


def publish_training_package(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
    request: SupportAITrainingPublishRequest,
) -> SupportAITrainingVersionResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    prompt, package_hash, cases, rules = _compiled_package(
        session,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )
    if not cases:
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_APPROVED_CASE_REQUIRED",
            "发布前至少批准一个训练案例。",
            kind="conflict",
        )
    active = session.scalar(
        select(SupportAITrainingVersionRow).where(
            SupportAITrainingVersionRow.agent_id == agent_id,
            (
                SupportAITrainingVersionRow.knowledge_base_id == knowledge_base_id
                if knowledge_base_id is not None
                else SupportAITrainingVersionRow.knowledge_base_id.is_(None)
            ),
            SupportAITrainingVersionRow.status == "PUBLISHED",
        )
    )
    if active is not None and active.package_hash == package_hash:
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_NO_CHANGES",
            "批准内容与当前发布版本一致，无需重复发布。",
            kind="conflict",
        )
    next_version = int(
        session.scalar(
            select(func.max(SupportAITrainingVersionRow.version_number)).where(
                SupportAITrainingVersionRow.agent_id == agent_id,
                (
                    SupportAITrainingVersionRow.knowledge_base_id == knowledge_base_id
                    if knowledge_base_id is not None
                    else SupportAITrainingVersionRow.knowledge_base_id.is_(None)
                ),
            )
        )
        or 0
    ) + 1
    now = utcnow()
    row = SupportAITrainingVersionRow(
        id=uuid4(),
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        version_number=next_version,
        status="RETIRED",
        package_hash=package_hash,
        compiled_prompt=prompt,
        case_snapshot=cases,
        rule_snapshot=rules,
        release_notes=request.release_notes,
        published_by_user_id=context.user_id,
        published_at=now,
        activated_at=now,
    )
    session.add(row)
    session.flush()
    _activate_version(
        session,
        context=context,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        version=row,
        user_id=context.user_id,
    )
    session.commit()
    return _version_response(row)


def approve_and_publish_training(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
) -> SupportAITrainingOverviewResponse:
    """Approve every draft and atomically activate the resulting package."""
    _require_platform_admin(context)
    _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    now = utcnow()
    for row in _cases(session, agent_id, knowledge_base_id):
        if row.status == "DRAFT":
            row.status = "APPROVED"
            row.updated_by_user_id = context.user_id
            row.updated_at = now
    for row in _rules(session, agent_id, knowledge_base_id):
        if row.status == "DRAFT":
            row.status = "APPROVED"
            row.updated_by_user_id = context.user_id
            row.updated_at = now
    session.flush()

    _, package_hash, cases, _ = _compiled_package(
        session,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )
    if not cases:
        session.rollback()
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_CASE_REQUIRED",
            "请先导入或新增至少一个训练案例。",
            kind="conflict",
        )
    active = session.scalar(
        select(SupportAITrainingVersionRow).where(
            SupportAITrainingVersionRow.agent_id == agent_id,
            (
                SupportAITrainingVersionRow.knowledge_base_id == knowledge_base_id
                if knowledge_base_id is not None
                else SupportAITrainingVersionRow.knowledge_base_id.is_(None)
            ),
            SupportAITrainingVersionRow.status == "PUBLISHED",
        )
    )
    if active is None or active.package_hash != package_hash:
        publish_training_package(
            session,
            context=context,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            request=SupportAITrainingPublishRequest(release_notes="一键审批并生效"),
        )
    else:
        session.commit()
    return get_training_overview(
        session,
        context=context,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )


def activate_training_version(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    version_id: UUID,
    knowledge_base_id: UUID | None = None,
) -> SupportAITrainingVersionResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    row = session.scalar(
        select(SupportAITrainingVersionRow).where(
            SupportAITrainingVersionRow.id == version_id,
            SupportAITrainingVersionRow.agent_id == agent_id,
            (
                SupportAITrainingVersionRow.knowledge_base_id == knowledge_base_id
                if knowledge_base_id is not None
                else SupportAITrainingVersionRow.knowledge_base_id.is_(None)
            ),
        )
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_VERSION_NOT_FOUND",
            "训练版本不存在。",
            kind="not_found",
        )
    _activate_version(
        session,
        context=context,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        version=row,
        user_id=context.user_id,
    )
    session.commit()
    return _version_response(row)


def export_training_package(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
) -> dict[str, Any]:
    _require_platform_admin(context)
    agent = _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    return {
        "schema_version": TRAINING_SCHEMA_VERSION,
        "agent": {
            "id": str(agent.id),
            "agent_code": agent.agent_code,
            "name": agent.name,
        },
        "boundary": TRAINING_BOUNDARY,
        "rules": [
            {
                "rule_key": row.rule_key,
                "title": row.title,
                "instruction": row.instruction,
                "scopes": list(row.scopes or []),
                "source_case_ids": list(row.source_case_ids or []),
                "priority": row.priority,
                "status": row.status,
            }
            for row in _rules(session, agent_id, knowledge_base_id)
        ],
        "cases": [
            {
                "external_id": row.external_id,
                "source_tenant_id": str(row.source_tenant_id) if row.source_tenant_id else None,
                "title": row.title,
                "language": row.language,
                "customer_message": row.customer_message,
                "ideal_response": row.ideal_response,
                "response_action": row.response_action,
                "grounding_mode": row.grounding_mode,
                "behavior_notes": row.behavior_notes,
                "required_evidence_types": list(row.required_evidence_types or []),
                "tags": list(row.tags or []),
                "forbidden_patterns": list(row.forbidden_patterns or []),
                "source_type": row.source_type,
                "status": row.status,
                "sort_order": row.sort_order,
            }
            for row in _cases(session, agent_id, knowledge_base_id)
        ],
    }


def import_training_package(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
    request: SupportAITrainingPackage,
) -> SupportAITrainingOverviewResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    bound_tenant_ids = set(
        _bound_tenant_ids(
            session,
            context=context,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
    )
    for item in request.cases:
        row = SupportAITrainingCaseRow(
            id=uuid4(),
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            source_tenant_id=(
                item.source_tenant_id
                if item.source_tenant_id in bound_tenant_ids
                else None
            ),
            external_id=_unique_external_id(
                session,
                agent_id=agent_id,
                knowledge_base_id=knowledge_base_id,
                preferred=item.external_id,
                prefix="import",
            ),
            title=item.title,
            language=item.language,
            customer_message=item.customer_message,
            ideal_response=item.ideal_response,
            response_action=item.response_action,
            grounding_mode=item.grounding_mode,
            behavior_notes=item.behavior_notes,
            required_evidence_types=list(item.required_evidence_types),
            tags=list(item.tags),
            forbidden_patterns=list(item.forbidden_patterns),
            source_type="IMPORT",
            status="DRAFT",
            sort_order=item.sort_order,
            created_by_user_id=context.user_id,
            updated_by_user_id=context.user_id,
        )
        session.add(row)
        session.flush()
    for item in request.rules:
        row = SupportAITrainingRuleRow(
            id=uuid4(),
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            rule_key=_unique_rule_key(
                session,
                agent_id=agent_id,
                knowledge_base_id=knowledge_base_id,
                preferred=item.rule_key,
            ),
            title=item.title,
            instruction=item.instruction,
            scopes=[scope for scope in item.scopes if scope in SUPPORTED_SCOPES],
            source_case_ids=[],
            priority=item.priority,
            status="DRAFT",
            created_by_user_id=context.user_id,
            updated_by_user_id=context.user_id,
        )
        session.add(row)
        session.flush()
    session.commit()
    return get_training_overview(
        session,
        context=context,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )


def copy_training_drafts(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    knowledge_base_id: UUID | None = None,
    request: SupportAITrainingCopyRequest,
) -> SupportAITrainingOverviewResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _knowledge_base(session, agent_id=agent_id, knowledge_base_id=knowledge_base_id)
    _agent(session, request.target_agent_id)
    target_knowledge_base_id = request.target_knowledge_base_id
    if knowledge_base_id is not None and target_knowledge_base_id is None:
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_COPY_TARGET_KNOWLEDGE_BASE_REQUIRED",
            "从知识库复制训练内容时，请指定目标知识库。",
            kind="conflict",
        )
    if target_knowledge_base_id is not None:
        _knowledge_base(
            session,
            agent_id=request.target_agent_id,
            knowledge_base_id=target_knowledge_base_id,
        )
    if request.target_agent_id == agent_id:
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_COPY_SAME_AGENT",
            "请选择另一个智能体作为复制目标。",
            kind="conflict",
        )
    if request.include_cases:
        for source in _cases(session, agent_id, knowledge_base_id):
            session.add(
                SupportAITrainingCaseRow(
                    id=uuid4(),
                    agent_id=request.target_agent_id,
                    knowledge_base_id=target_knowledge_base_id,
                    external_id=_unique_external_id(
                        session,
                        agent_id=request.target_agent_id,
                        knowledge_base_id=target_knowledge_base_id,
                        preferred=source.external_id,
                        prefix="copy",
                    ),
                    title=source.title,
                    language=source.language,
                    customer_message=source.customer_message,
                    ideal_response=source.ideal_response,
                    response_action=source.response_action,
                    grounding_mode=source.grounding_mode,
                    behavior_notes=source.behavior_notes,
                    required_evidence_types=list(source.required_evidence_types or []),
                    tags=list(source.tags or []),
                    forbidden_patterns=list(source.forbidden_patterns or []),
                    source_type="IMPORT",
                    status="DRAFT",
                    sort_order=source.sort_order,
                    created_by_user_id=context.user_id,
                    updated_by_user_id=context.user_id,
                )
            )
            session.flush()
    if request.include_rules:
        for source in _rules(session, agent_id, knowledge_base_id):
            session.add(
                SupportAITrainingRuleRow(
                    id=uuid4(),
                    agent_id=request.target_agent_id,
                    knowledge_base_id=target_knowledge_base_id,
                    rule_key=_unique_rule_key(
                        session,
                        agent_id=request.target_agent_id,
                        knowledge_base_id=target_knowledge_base_id,
                        preferred=source.rule_key,
                    ),
                    title=source.title,
                    instruction=source.instruction,
                    scopes=list(source.scopes or []),
                    source_case_ids=[],
                    priority=source.priority,
                    status="DRAFT",
                    created_by_user_id=context.user_id,
                    updated_by_user_id=context.user_id,
                )
            )
            session.flush()
    session.commit()
    return get_training_overview(
        session,
        context=context,
        agent_id=request.target_agent_id,
        knowledge_base_id=target_knowledge_base_id,
    )
