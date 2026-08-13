from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
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
from ..repositories import public_catalog_repository
from ..services.auth.dependencies import RequestContext
from ..services.chat_generation import ChatGenerationError
from ..services.support_ai_configuration import resolved_support_ai_provider
from ..services.support_ai_retrieval import _public_product_excerpt
from ..support_ai_models import (
    SupportAIAgentRow,
    SupportAISettingsRow,
    SupportAITrainingCaseRow,
    SupportAITrainingRuleRow,
    SupportAITrainingVersionRow,
)
from ..support_ai_schemas import (
    SupportAITrainingCaseResponse,
    SupportAITrainingCaseWrite,
    SupportAITrainingCopyRequest,
    SupportAITrainingGenerateRequest,
    SupportAITrainingGenerateResponse,
    SupportAITrainingOverviewResponse,
    SupportAITrainingPackage,
    SupportAITrainingPreviewResponse,
    SupportAITrainingPublishRequest,
    SupportAITrainingRuleResponse,
    SupportAITrainingRuleWrite,
    SupportAITrainingSummarizeRequest,
    SupportAITrainingSummarizeResponse,
    SupportAITrainingVersionResponse,
)


TRAINING_SCHEMA_VERSION = "support-ai-training/v1"
TRAINING_BOUNDARY = [
    "Training cases and rules teach response behavior; they are not merchant-fact evidence.",
    "Product facts such as price, MOQ, stock, specification and product code must come from current approved evidence.",
    "A published example may be imitated structurally, but its facts, numbers, citations and identifiers must never be copied into another answer.",
    "Imported and generated material remains draft until a platform administrator explicitly approves and publishes it.",
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


def _cases(session: Session, agent_id: UUID) -> list[SupportAITrainingCaseRow]:
    return list(
        session.scalars(
            select(SupportAITrainingCaseRow)
            .where(SupportAITrainingCaseRow.agent_id == agent_id)
            .order_by(
                SupportAITrainingCaseRow.sort_order,
                SupportAITrainingCaseRow.updated_at.desc(),
            )
        ).all()
    )


def _rules(session: Session, agent_id: UUID) -> list[SupportAITrainingRuleRow]:
    return list(
        session.scalars(
            select(SupportAITrainingRuleRow)
            .where(SupportAITrainingRuleRow.agent_id == agent_id)
            .order_by(
                SupportAITrainingRuleRow.priority.desc(),
                SupportAITrainingRuleRow.updated_at.desc(),
            )
        ).all()
    )


def _versions(
    session: Session, agent_id: UUID
) -> list[SupportAITrainingVersionRow]:
    return list(
        session.scalars(
            select(SupportAITrainingVersionRow)
            .where(SupportAITrainingVersionRow.agent_id == agent_id)
            .order_by(SupportAITrainingVersionRow.version_number.desc())
        ).all()
    )


def get_training_overview(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
) -> SupportAITrainingOverviewResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    cases = _cases(session, agent_id)
    rules = _rules(session, agent_id)
    versions = _versions(session, agent_id)
    active = next((row for row in versions if row.status == "PUBLISHED"), None)
    return SupportAITrainingOverviewResponse(
        agent_id=agent_id,
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
    preferred: str | None,
    prefix: str,
) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", preferred or "").strip("-.")
    base = (normalized or f"{prefix}-{uuid4().hex[:12]}")[:110]
    candidate = base
    for suffix in range(1, 1000):
        exists = session.scalar(
            select(SupportAITrainingCaseRow.id)
            .execution_options(include_deleted=True)
            .where(
                SupportAITrainingCaseRow.agent_id == agent_id,
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
    preferred: str | None,
) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", preferred or "").strip("-.")
    base = (normalized or f"rule-{uuid4().hex[:12]}")[:110]
    candidate = base
    for suffix in range(1, 1000):
        exists = session.scalar(
            select(SupportAITrainingRuleRow.id)
            .execution_options(include_deleted=True)
            .where(
                SupportAITrainingRuleRow.agent_id == agent_id,
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
    request: SupportAITrainingCaseWrite,
) -> SupportAITrainingCaseResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _validate_case_source_tenant(
        session,
        context=context,
        agent_id=agent_id,
        source_tenant_id=request.source_tenant_id,
    )
    row = SupportAITrainingCaseRow(
        id=uuid4(),
        agent_id=agent_id,
        external_id=_unique_external_id(
            session,
            agent_id=agent_id,
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
    request: SupportAITrainingCaseWrite,
) -> SupportAITrainingCaseResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    row = session.scalar(
        select(SupportAITrainingCaseRow).where(
            SupportAITrainingCaseRow.id == case_id,
            SupportAITrainingCaseRow.agent_id == agent_id,
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
) -> None:
    _require_platform_admin(context)
    _agent(session, agent_id)
    row = session.scalar(
        select(SupportAITrainingCaseRow).where(
            SupportAITrainingCaseRow.id == case_id,
            SupportAITrainingCaseRow.agent_id == agent_id,
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
    request: SupportAITrainingRuleWrite,
) -> SupportAITrainingRuleResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    row = SupportAITrainingRuleRow(
        id=uuid4(),
        agent_id=agent_id,
        rule_key=_unique_rule_key(
            session, agent_id=agent_id, preferred=request.rule_key
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
    request: SupportAITrainingRuleWrite,
) -> SupportAITrainingRuleResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    row = session.scalar(
        select(SupportAITrainingRuleRow).where(
            SupportAITrainingRuleRow.id == rule_id,
            SupportAITrainingRuleRow.agent_id == agent_id,
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
) -> None:
    _require_platform_admin(context)
    _agent(session, agent_id)
    row = session.scalar(
        select(SupportAITrainingRuleRow).where(
            SupportAITrainingRuleRow.id == rule_id,
            SupportAITrainingRuleRow.agent_id == agent_id,
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
) -> list[UUID]:
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
    source_tenant_id: UUID | None,
    existing_source_tenant_id: UUID | None = None,
) -> None:
    if source_tenant_id is None or source_tenant_id == existing_source_tenant_id:
        return
    if source_tenant_id not in _bound_tenant_ids(
        session,
        context=context,
        agent_id=agent_id,
    ):
        raise ApplicationError(
            "SUPPORT_AI_AGENT_STORE_NOT_BOUND",
            "案例来源店铺未绑定到该智能体。",
            kind="conflict",
        )


def _catalog_training_products(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    tenant_id: UUID | None,
    limit: int = 32,
) -> tuple[UUID, list[dict[str, str]]]:
    bound_ids = _bound_tenant_ids(
        session,
        context=context,
        agent_id=agent_id,
    )
    if not bound_ids:
        raise ApplicationError(
            "SUPPORT_AI_AGENT_STORE_REQUIRED",
            "请先为智能体绑定至少一个店铺。",
            kind="conflict",
        )
    selected_tenant_id = tenant_id or bound_ids[0]
    if selected_tenant_id not in bound_ids:
        raise ApplicationError(
            "SUPPORT_AI_AGENT_STORE_NOT_BOUND",
            "所选店铺未绑定到该智能体。",
            kind="conflict",
        )
    tenant = _tenant(session, selected_tenant_id)
    with _tenant_scope(session, context=context, tenant=tenant):
        product_ids = public_catalog_repository.list_public_catalog_product_ids(
            session,
            tenant_id=tenant.id,
            now=utcnow(),
        )[:limit]
        rows = public_catalog_repository.list_public_catalog_rows_for_products(
            session,
            tenant_id=tenant.id,
            now=utcnow(),
            product_ids=product_ids,
        )
    grouped: dict[UUID, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[row[2].id].append(row)
    products = [
        {
            "product_id": str(product_id),
            "title": str(product_rows[0][2].name)[:500],
            "approved_public_facts": _public_product_excerpt(product_rows),
        }
        for product_id, product_rows in grouped.items()
    ]
    if not products:
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_PRODUCTS_EMPTY",
            "绑定店铺暂无可对客展示的商品，无法生成商品案例。",
            kind="conflict",
        )
    return selected_tenant_id, products


def _provider_generate_json(
    provider: Any,
    *,
    messages: list[dict[str, str]],
    max_output_tokens: int,
) -> dict[str, Any]:
    kwargs = {
        "messages": messages,
        "temperature": 0.25,
        "max_output_tokens": max_output_tokens,
    }
    stream = getattr(provider, "generate_json_stream", None)
    result = stream(**kwargs) if callable(stream) else provider.generate_json(**kwargs)
    return result.data


def _case_payload(value: Any, *, language: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    title = str(value.get("title") or "").strip()[:240]
    customer_message = str(value.get("customer_message") or "").strip()[:4000]
    ideal_response = str(value.get("ideal_response") or "").strip()[:12000]
    if not (title and customer_message and ideal_response):
        return None
    response_action = str(value.get("response_action") or "ANSWER").upper()
    if response_action not in {"ANSWER", "CLARIFY", "HANDOFF"}:
        response_action = "ANSWER"
    grounding_mode = str(value.get("grounding_mode") or "EVIDENCE").upper()
    if grounding_mode not in {
        "EVIDENCE",
        "GENERAL_GUIDANCE",
        "APPROVED_COMPANY_PROFILE",
    }:
        grounding_mode = "EVIDENCE"
    required = [
        item
        for item in [str(item).upper() for item in value.get("required_evidence_types") or []]
        if item in {"SKU", "FILE", "COMPANY_PROFILE"}
    ]
    return {
        "title": title,
        "language": str(value.get("language") or language).strip()[:35] or language,
        "customer_message": customer_message,
        "ideal_response": ideal_response,
        "response_action": response_action,
        "grounding_mode": grounding_mode,
        "behavior_notes": str(value.get("behavior_notes") or "").strip()[:6000] or None,
        "required_evidence_types": list(dict.fromkeys(required)),
        "tags": list(
            dict.fromkeys(
                str(item).strip()[:240]
                for item in value.get("tags") or []
                if str(item).strip()
            )
        )[:20],
        "forbidden_patterns": list(
            dict.fromkeys(
                str(item).strip()[:240]
                for item in value.get("forbidden_patterns") or []
                if str(item).strip()
            )
        )[:20],
    }


def _template_cases(
    products: list[dict[str, str]],
    *,
    count: int,
    languages: list[str],
) -> list[dict[str, Any]]:
    patterns = [
        (
            "场景推荐",
            "我想买{product}，你能先告诉我它适合什么使用场景吗？",
            "先给出基于当前商品证据的直接判断，并引用对应商品；若证据缺少关键场景信息，再提出一个最有区分度的追问。",
            "PRODUCT_RECOMMENDATION",
        ),
        (
            "MOQ 与价格",
            "{product}的价格和起订量是多少？",
            "只复述当前 SKU 证据中的公开价格、币种、MOQ 和单位；每个数字都紧邻引用，缺失字段明确说暂未提供。",
            "MOQ_PRICE",
        ),
        (
            "规格确认",
            "请介绍一下{product}的规格和可选项。",
            "按客户当前语言简洁整理证据中的规格、材质和选项，并引用商品；不展示供应商或内部字段。",
            "SPECIFICATION",
        ),
        (
            "信息不足追问",
            "我需要这个类型的产品，但还没有想好具体规格。",
            "先说明可以协助筛选，再只询问用途、尺寸、材质、预算或数量中最关键的一项；不要因为信息不足直接转人工。",
            "CLARIFICATION",
        ),
        (
            "同类比较",
            "{product}和同类商品相比怎么选？",
            "若有多个当前商品证据，先推荐一个主选项、最多一个备选并解释差异；证据不足时说明比较维度并追问，禁止编造优缺点。",
            "COMPARISON",
        ),
    ]
    result: list[dict[str, Any]] = []
    for index in range(count):
        product = products[index % len(products)]
        title, question, response, tag = patterns[index % len(patterns)]
        language = languages[index % len(languages)]
        if not language.casefold().startswith("zh"):
            question = f"Please help me understand and choose {product['title']}."
            response = (
                "Reply in the customer's language. Use current approved SKU evidence for "
                "all merchant-specific facts, give a useful first recommendation, cite it, "
                "and ask one focused follow-up only when it improves the choice."
            )
        result.append(
            {
                "title": f"{title} · {product['title']}"[:240],
                "language": language,
                "customer_message": question.format(product=product["title"]),
                "ideal_response": response,
                "response_action": "CLARIFY" if tag == "CLARIFICATION" else "ANSWER",
                "grounding_mode": "GENERAL_GUIDANCE" if tag == "CLARIFICATION" else "EVIDENCE",
                "behavior_notes": "案例用于学习回答策略；商品事实必须在运行时从当前证据重新读取。",
                "required_evidence_types": [] if tag == "CLARIFICATION" else ["SKU"],
                "tags": [tag, "PRODUCT_BASED"],
                "forbidden_patterns": ["复制案例中的过期数字", "泄露供应商或内部字段", "无依据承诺库存"],
            }
        )
    return result


def generate_training_cases(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    request: SupportAITrainingGenerateRequest,
) -> SupportAITrainingGenerateResponse:
    _require_platform_admin(context)
    agent = _agent(session, agent_id)
    tenant_id, products = _catalog_training_products(
        session,
        context=context,
        agent_id=agent_id,
        tenant_id=request.tenant_id,
    )
    generated: list[dict[str, Any]] = []
    generation_mode = "MODEL"
    try:
        provider = resolved_support_ai_provider(
            session,
            profile_id=agent.provider_setting_id,
        )
        product_payload = products[: min(len(products), 24)]
        messages = [
            {
                "role": "system",
                "content": (
                    "You create supervised training examples for a commerce customer-support agent. "
                    "Return one JSON object with a cases array. Each case must contain title, language, "
                    "customer_message, ideal_response, response_action, grounding_mode, behavior_notes, "
                    "required_evidence_types, tags and forbidden_patterns. Generate varied recommendation, "
                    "comparison, specification, MOQ/price, ambiguous-intent and multilingual examples. "
                    "The ideal_response is a behavior exemplar: it may use only supplied public facts and "
                    "must cite evidence as [1]. Never expose supplier identity, supplier SKU, supplier score, "
                    "cost, margin or internal notes. Never treat omitted facts as negative facts. Information "
                    "gaps normally lead to one useful clarifying question, not human handoff. Handoff is only "
                    "for an explicit human request or a genuinely human-only action."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "requested_count": request.count,
                        "languages": request.languages,
                        "boundary": TRAINING_BOUNDARY,
                        "approved_public_products": product_payload,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ]
        data = _provider_generate_json(
            provider,
            messages=messages,
            max_output_tokens=min(12000, max(2400, request.count * 500)),
        )
        raw_cases = data.get("cases") if isinstance(data, dict) else None
        for index, raw in enumerate(raw_cases or []):
            payload = _case_payload(
                raw,
                language=request.languages[index % len(request.languages)],
            )
            if payload is not None:
                generated.append(payload)
            if len(generated) >= request.count:
                break
        if len(generated) < max(1, min(3, request.count)):
            raise ChatGenerationError("model returned too few valid training cases")
        if len(generated) < request.count:
            generated.extend(
                _template_cases(
                    products,
                    count=request.count - len(generated),
                    languages=request.languages,
                )
            )
    except (ChatGenerationError, TypeError, ValueError):
        generation_mode = "TEMPLATE_FALLBACK"
        generated = _template_cases(
            products,
            count=request.count,
            languages=request.languages,
        )

    items: list[SupportAITrainingCaseRow] = []
    for index, payload in enumerate(generated[: request.count]):
        row = SupportAITrainingCaseRow(
            id=uuid4(),
            agent_id=agent_id,
            source_tenant_id=tenant_id,
            external_id=_unique_external_id(
                session,
                agent_id=agent_id,
                preferred=None,
                prefix="product",
            ),
            title=payload["title"],
            language=payload["language"],
            customer_message=payload["customer_message"],
            ideal_response=payload["ideal_response"],
            response_action=payload["response_action"],
            grounding_mode=payload["grounding_mode"],
            behavior_notes=payload["behavior_notes"],
            required_evidence_types=payload["required_evidence_types"],
            tags=payload["tags"],
            forbidden_patterns=payload["forbidden_patterns"],
            source_type="PRODUCT_GENERATED",
            status="DRAFT",
            sort_order=index,
            created_by_user_id=context.user_id,
            updated_by_user_id=context.user_id,
        )
        session.add(row)
        session.flush()
        items.append(row)
    session.commit()
    return SupportAITrainingGenerateResponse(
        items=[_case_response(row) for row in items],
        generation_mode=generation_mode,
        product_count=len(products),
    )


FALLBACK_RULES = [
    (
        "evidence-first",
        "商品事实以实时证据为准",
        "涉及商品、规格、价格、币种、MOQ、库存或交期时，只能使用本次检索到的已批准证据；案例中的事实和数字不得复用。",
        ["QUESTION_ANSWERING", "PRODUCT_RECOMMENDATION"],
    ),
    (
        "recommend-before-question",
        "推荐优先于泛化追问",
        "当证据中已有合理候选时，先给出一个主推荐及理由，再提出最多一个能改善选择的具体追问；不要重复索要客户已经说明的信息。",
        ["PRODUCT_RECOMMENDATION", "CLARIFICATION"],
    ),
    (
        "no-match-clarify",
        "检索不足不等于转人工",
        "检索无匹配或证据不足时，提供安全的一般性选型思路并询问一个关键条件；除非客户明确要求人工或请求必须由人工执行，否则继续由 AI 处理。",
        ["QUESTION_ANSWERING", "CLARIFICATION", "HANDOFF"],
    ),
    (
        "language-mirror",
        "严格跟随客户当前语言",
        "识别客户最后一条消息实际使用的语言，并使用同一种语言回答；商品名称和编码可保留原文。",
        ["MULTILINGUAL", "QUESTION_ANSWERING", "PRODUCT_RECOMMENDATION"],
    ),
    (
        "citation-near-claim",
        "引用紧邻事实",
        "每项关键商品事实后紧邻对应引用；不要用一个悬空引用支撑多项来源不明的事实。",
        ["QUESTION_ANSWERING", "PRODUCT_RECOMMENDATION"],
    ),
    (
        "protect-internal-fields",
        "隔离内部供应链字段",
        "不得向客户披露供应商名称、供应商 SKU、供应商评分、成本、利润、联系人或内部备注；MOQ 属于可回答的商品信息，但必须来自当前证据。",
        ["QUESTION_ANSWERING", "PRODUCT_RECOMMENDATION"],
    ),
    (
        "one-focused-question",
        "一次只问关键问题",
        "需要补充信息时，只问当前最能缩小选择范围的一项，例如用途、尺寸、材质、预算或数量，避免机械重复完整问题清单。",
        ["CLARIFICATION", "PRODUCT_RECOMMENDATION"],
    ),
    (
        "honest-uncertainty",
        "区分缺失与否定",
        "资料未提供某字段时应表达为暂未提供或需要确认，不得推断为没有、免费、无限库存或无最低起订量。",
        ["QUESTION_ANSWERING", "PRODUCT_RECOMMENDATION"],
    ),
]


def _rule_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    title = str(value.get("title") or "").strip()[:240]
    instruction = str(value.get("instruction") or "").strip()[:6000]
    if not title or not instruction:
        return None
    scopes = [
        scope
        for scope in [str(item).upper() for item in value.get("scopes") or []]
        if scope in SUPPORTED_SCOPES
    ]
    return {
        "rule_key": str(value.get("rule_key") or "").strip()[:120] or None,
        "title": title,
        "instruction": instruction,
        "scopes": list(dict.fromkeys(scopes)),
        "source_case_ids": [],
        "priority": max(0, min(1000, int(value.get("priority") or 100))),
    }


def summarize_training_rules(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    request: SupportAITrainingSummarizeRequest,
) -> SupportAITrainingSummarizeResponse:
    _require_platform_admin(context)
    agent = _agent(session, agent_id)
    selected_ids = set(request.case_ids)
    cases = [
        row
        for row in _cases(session, agent_id)
        if not selected_ids or row.id in selected_ids
    ]
    if not cases:
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_CASE_REQUIRED",
            "请先创建或生成训练案例。",
            kind="conflict",
        )
    generated: list[dict[str, Any]] = []
    generation_mode = "MODEL"
    try:
        provider = resolved_support_ai_provider(
            session,
            profile_id=agent.provider_setting_id,
        )
        payload = [
            {
                "id": str(row.id),
                "question": row.customer_message,
                "ideal_behavior": row.ideal_response,
                "notes": row.behavior_notes,
                "action": row.response_action,
                "grounding": row.grounding_mode,
                "tags": row.tags,
            }
            for row in cases[:80]
        ]
        data = _provider_generate_json(
            provider,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Distill reusable customer-support behavior rules from reviewed examples. "
                        "Return one JSON object with a rules array. Each rule has rule_key, title, "
                        "instruction, scopes and priority. Rules must be general, actionable and "
                        "non-overlapping. Never copy a product name, product code, SKU, price, MOQ, "
                        "specification, citation number or other merchant fact into a rule. Preserve "
                        "the boundary that training teaches behavior while current approved evidence "
                        "supplies facts."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "maximum_rules": request.max_rules,
                            "boundary": TRAINING_BOUNDARY,
                            "examples": payload,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
            max_output_tokens=min(7000, max(1800, request.max_rules * 500)),
        )
        for raw in data.get("rules") or []:
            item = _rule_payload(raw)
            if item is not None:
                generated.append(item)
            if len(generated) >= request.max_rules:
                break
        if not generated:
            raise ChatGenerationError("model returned no valid training rules")
    except (ChatGenerationError, TypeError, ValueError):
        generation_mode = "TEMPLATE_FALLBACK"
        generated = [
            {
                "rule_key": key,
                "title": title,
                "instruction": instruction,
                "scopes": scopes,
                "source_case_ids": [],
                "priority": 200 - index * 10,
            }
            for index, (key, title, instruction, scopes) in enumerate(
                FALLBACK_RULES[: request.max_rules]
            )
        ]

    case_ids = [str(row.id) for row in cases]
    items: list[SupportAITrainingRuleRow] = []
    for item in generated[: request.max_rules]:
        row = SupportAITrainingRuleRow(
            id=uuid4(),
            agent_id=agent_id,
            rule_key=_unique_rule_key(
                session,
                agent_id=agent_id,
                preferred=item.get("rule_key"),
            ),
            title=item["title"],
            instruction=item["instruction"],
            scopes=item["scopes"],
            source_case_ids=case_ids,
            priority=item["priority"],
            status="DRAFT",
            created_by_user_id=context.user_id,
            updated_by_user_id=context.user_id,
        )
        session.add(row)
        session.flush()
        items.append(row)
    session.commit()
    return SupportAITrainingSummarizeResponse(
        items=[_rule_response(row) for row in items],
        generation_mode=generation_mode,
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
) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]]:
    approved_cases = [row for row in _cases(session, agent_id) if row.status == "APPROVED"]
    approved_rules = [row for row in _rules(session, agent_id) if row.status == "APPROVED"]
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
) -> SupportAITrainingPreviewResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    prompt, package_hash, cases, rules = _compiled_package(
        session, agent_id=agent_id
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
    version: SupportAITrainingVersionRow,
    user_id: UUID,
) -> None:
    now = utcnow()
    for row in _versions(session, agent_id):
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
    request: SupportAITrainingPublishRequest,
) -> SupportAITrainingVersionResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    prompt, package_hash, cases, rules = _compiled_package(session, agent_id=agent_id)
    if not cases:
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_APPROVED_CASE_REQUIRED",
            "发布前至少批准一个训练案例。",
            kind="conflict",
        )
    active = session.scalar(
        select(SupportAITrainingVersionRow).where(
            SupportAITrainingVersionRow.agent_id == agent_id,
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
                SupportAITrainingVersionRow.agent_id == agent_id
            )
        )
        or 0
    ) + 1
    now = utcnow()
    row = SupportAITrainingVersionRow(
        id=uuid4(),
        agent_id=agent_id,
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
        version=row,
        user_id=context.user_id,
    )
    session.commit()
    return _version_response(row)


def activate_training_version(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    version_id: UUID,
) -> SupportAITrainingVersionResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    row = session.scalar(
        select(SupportAITrainingVersionRow).where(
            SupportAITrainingVersionRow.id == version_id,
            SupportAITrainingVersionRow.agent_id == agent_id,
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
) -> dict[str, Any]:
    _require_platform_admin(context)
    agent = _agent(session, agent_id)
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
            for row in _rules(session, agent_id)
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
            for row in _cases(session, agent_id)
        ],
    }


def import_training_package(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    request: SupportAITrainingPackage,
) -> SupportAITrainingOverviewResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    bound_tenant_ids = set(
        _bound_tenant_ids(
            session,
            context=context,
            agent_id=agent_id,
        )
    )
    for item in request.cases:
        row = SupportAITrainingCaseRow(
            id=uuid4(),
            agent_id=agent_id,
            source_tenant_id=(
                item.source_tenant_id
                if item.source_tenant_id in bound_tenant_ids
                else None
            ),
            external_id=_unique_external_id(
                session,
                agent_id=agent_id,
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
            rule_key=_unique_rule_key(
                session, agent_id=agent_id, preferred=item.rule_key
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
    return get_training_overview(session, context=context, agent_id=agent_id)


def copy_training_drafts(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    request: SupportAITrainingCopyRequest,
) -> SupportAITrainingOverviewResponse:
    _require_platform_admin(context)
    _agent(session, agent_id)
    _agent(session, request.target_agent_id)
    if request.target_agent_id == agent_id:
        raise ApplicationError(
            "SUPPORT_AI_TRAINING_COPY_SAME_AGENT",
            "请选择另一个智能体作为复制目标。",
            kind="conflict",
        )
    if request.include_cases:
        for source in _cases(session, agent_id):
            session.add(
                SupportAITrainingCaseRow(
                    id=uuid4(),
                    agent_id=request.target_agent_id,
                    external_id=_unique_external_id(
                        session,
                        agent_id=request.target_agent_id,
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
        for source in _rules(session, agent_id):
            session.add(
                SupportAITrainingRuleRow(
                    id=uuid4(),
                    agent_id=request.target_agent_id,
                    rule_key=_unique_rule_key(
                        session,
                        agent_id=request.target_agent_id,
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
    )
