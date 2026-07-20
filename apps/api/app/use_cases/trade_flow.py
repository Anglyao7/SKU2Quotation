from __future__ import annotations

import hashlib
import json
from datetime import UTC, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..repositories import trade_flow_repository as repository
from ..services.hybrid_search import hybrid_product_search
from ..model_mixins import utcnow
from ..product_intelligence_models import OutboxEventRow
from ..trade_flow_models import CustomerRow, InquiryItemRow, InquiryMatchResultRow, InquiryRow, QuotationApprovalRow, QuotationItemRow, QuotationRow, QuotationVersionRow
from ..trade_flow_schemas import CandidateSelectRequest, CustomerCreateRequest, CustomerResponse, InquiryCreateRequest, InquiryItemConfirmRequest, InquiryItemResponse, InquiryMatchResponse, InquiryResponse, MatchResultResponse, QuotationCreateRequest, QuotationDecisionRequest, QuotationItemResponse, QuotationResponse, QuotationRevisionRequest, QuotationSummary, QuotationVersionSummary


MIN_MARGIN = Decimal("0.15")
RULE_VERSION = "atc-deterministic-margin-v1"


def _require(permissions: frozenset[str], code: str) -> None:
    if code not in permissions:
        raise ApplicationError("PERMISSION_DENIED", f"Permission is required: {code}", kind="forbidden")


def _jsonable(value):
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def create_customer(session: Session, *, tenant_id: UUID, permissions: frozenset[str], request: CustomerCreateRequest) -> CustomerResponse:
    _require(permissions, "customer.manage")
    row = CustomerRow(tenant_id=tenant_id, customer_code=(request.customer_code or f"CUS-{uuid4().hex[:10]}").upper(), company_name=request.company_name.strip(), country_code=request.country_code.upper() if request.country_code else None, language=request.language, default_currency=request.default_currency.upper(), status="ACTIVE")
    session.add(row); session.commit()
    return CustomerResponse(id=row.id, customer_code=row.customer_code, company_name=row.company_name, country_code=row.country_code, language=row.language, default_currency=row.default_currency, status=row.status)


def _item_response(row: InquiryItemRow) -> InquiryItemResponse:
    return InquiryItemResponse(id=row.id, line_number=row.line_number, raw_requirement=row.raw_requirement, normalized_requirement=row.normalized_requirement, quantity=row.quantity, unit_code=row.unit_code, target_price=row.target_price, target_currency=row.target_currency, image_search_id=row.image_search_id, status=row.status, version=row.version)


def _inquiry_response(session: Session, row: InquiryRow) -> InquiryResponse:
    return InquiryResponse(id=row.id, inquiry_number=row.inquiry_number, customer_id=row.customer_id, temporary_customer_name=row.temporary_customer_name, currency=row.currency, language=row.language, status=row.status, version=row.version, items=[_item_response(item) for item in repository.list_inquiry_items(session, tenant_id=row.tenant_id, inquiry_id=row.id)])


def create_inquiry(session: Session, *, tenant_id: UUID, membership_id: UUID, permissions: frozenset[str], request: InquiryCreateRequest) -> InquiryResponse:
    _require(permissions, "inquiry.manage")
    if request.customer_id and repository.get_customer(session, tenant_id=tenant_id, customer_id=request.customer_id) is None:
        raise ApplicationError("CUSTOMER_NOT_FOUND", "Customer was not found.", kind="not_found")
    all_complete = all(item.quantity is not None and item.unit_code for item in request.items)
    row = InquiryRow(tenant_id=tenant_id, inquiry_number=f"INQ-{utcnow():%Y%m%d}-{uuid4().hex[:8].upper()}", customer_id=request.customer_id, temporary_customer_name=request.temporary_customer_name, source_type=request.source_type.upper(), currency=request.currency.upper(), language=request.language, status="MATCHING" if all_complete else "NEEDS_REVIEW", owner_membership_id=membership_id, version=1)
    session.add(row); session.flush()
    for line, item in enumerate(request.items, 1):
        session.add(InquiryItemRow(tenant_id=tenant_id, inquiry_id=row.id, line_number=line, raw_requirement=item.requirement.strip(), normalized_requirement={"query": item.requirement.strip()}, quantity=item.quantity, unit_code=item.unit_code, target_price=item.target_price, target_currency=item.target_currency.upper() if item.target_currency else None, image_search_id=item.image_search_id, status="CONFIRMED" if item.quantity is not None and item.unit_code else "DRAFT", version=1))
    session.commit()
    return _inquiry_response(session, row)


def get_inquiry(session: Session, *, tenant_id: UUID, permissions: frozenset[str], inquiry_id: UUID) -> InquiryResponse:
    _require(permissions, "inquiry.view")
    row = repository.get_inquiry(session, tenant_id=tenant_id, inquiry_id=inquiry_id)
    if row is None:
        raise ApplicationError("INQUIRY_NOT_FOUND", "Inquiry was not found.", kind="not_found")
    return _inquiry_response(session, row)


def confirm_item(session: Session, *, tenant_id: UUID, permissions: frozenset[str], item_id: UUID, request: InquiryItemConfirmRequest) -> InquiryItemResponse:
    _require(permissions, "inquiry.manage")
    row = repository.get_inquiry_item(session, tenant_id=tenant_id, item_id=item_id)
    if row is None:
        raise ApplicationError("INQUIRY_ITEM_NOT_FOUND", "Inquiry item was not found.", kind="not_found")
    if row.version != request.expected_version:
        raise ApplicationError("VERSION_CONFLICT", "Inquiry item changed; refresh before confirming.", kind="conflict")
    row.normalized_requirement = request.normalized_requirement; row.quantity = request.quantity; row.unit_code = request.unit_code; row.status = "CONFIRMED"; row.version += 1
    inquiry = repository.get_inquiry(session, tenant_id=tenant_id, inquiry_id=row.inquiry_id)
    assert inquiry is not None
    items = repository.list_inquiry_items(session, tenant_id=tenant_id, inquiry_id=inquiry.id)
    if all(item.id == row.id or item.status != "DRAFT" for item in items):
        inquiry.status = "MATCHING"; inquiry.version += 1
    session.commit(); return _item_response(row)


def _match_response(row: InquiryMatchResultRow) -> MatchResultResponse:
    return MatchResultResponse(id=row.id, inquiry_item_id=row.inquiry_item_id, product_id=row.product_id, sku_id=row.sku_id, supplier_product_id=row.supplier_product_id, product_version=row.product_version, rank=row.rank, total_score=float(row.total_score), score_breakdown=row.score_breakdown, reasons=row.reasons, gaps=row.gaps, evidence=row.evidence, ranking_version=row.ranking_version, status=row.status)


def match_inquiry(session: Session, *, tenant_id: UUID, permissions: frozenset[str], inquiry_id: UUID, limit: int = 5) -> InquiryMatchResponse:
    _require(permissions, "inquiry.manage")
    inquiry = repository.get_inquiry(session, tenant_id=tenant_id, inquiry_id=inquiry_id)
    if inquiry is None:
        raise ApplicationError("INQUIRY_NOT_FOUND", "Inquiry was not found.", kind="not_found")
    items = repository.list_inquiry_items(session, tenant_id=tenant_id, inquiry_id=inquiry.id)
    if any(item.status == "DRAFT" or item.quantity is None for item in items):
        raise ApplicationError("INQUIRY_REVIEW_REQUIRED", "All inquiry lines require confirmed quantity and units.", kind="conflict")
    ranking_version = f"inquiry-hybrid-v1-{uuid4().hex[:8]}"; output: dict[str, list[MatchResultResponse]] = {}
    for item in items:
        for old in repository.list_candidates(session, tenant_id=tenant_id, item_id=item.id):
            if old.status == "CANDIDATE": old.status = "REJECTED"
        query = str(item.normalized_requirement.get("query") or item.raw_requirement)
        merged: dict[UUID, dict] = {}
        for product in repository.find_exact_products(session, tenant_id=tenant_id, query=query, limit=limit):
            exact = product.product_code and product.product_code.lower() == query.lower()
            merged[product.id] = {"product": product, "score": Decimal("1.0" if exact else "0.72"), "breakdown": {"exact": 1.0 if exact else 0.0, "keyword": 1.0}, "reasons": ["精确产品编码命中" if exact else "产品名称关键词命中"], "gaps": [], "evidence": [{"type": "PRODUCT_FACT", "product_version": product.current_version}]}
        try:
            hybrid = hybrid_product_search(session, tenant_id=tenant_id, query=query, limit=limit)
        except ValueError:
            hybrid = {"results": []}
        for result in hybrid.get("results", []):
            product_id = UUID(str(result["product_id"])); product = repository.get_product(session, tenant_id=tenant_id, product_id=product_id)
            if product is None: continue
            candidate = merged.setdefault(product_id, {"product": product, "score": Decimal("0"), "breakdown": {}, "reasons": [], "gaps": [], "evidence": []})
            score = Decimal(str(result["score"])); candidate["score"] = max(candidate["score"], score); candidate["breakdown"].update(_jsonable(result.get("score_breakdown", {}))); candidate["reasons"].append("文本知识库混合检索"); candidate["evidence"].extend(_jsonable(result.get("evidence", [])))
        if item.image_search_id:
            image_search = repository.get_image_search(session, tenant_id=tenant_id, search_id=item.image_search_id)
            if image_search and image_search.status == "COMPLETED":
                for visual in image_search.result_snapshot:
                    product_id = UUID(str(visual["product_id"])); product = repository.get_product(session, tenant_id=tenant_id, product_id=product_id)
                    if product is None: continue
                    candidate = merged.setdefault(product_id, {"product": product, "score": Decimal("0"), "breakdown": {}, "reasons": [], "gaps": [], "evidence": []})
                    visual_score = Decimal(str(visual["visual_similarity"])); candidate["score"] = min(Decimal("1"), candidate["score"] * Decimal("0.75") + visual_score * Decimal("0.25")); candidate["breakdown"]["image"] = float(visual_score); candidate["reasons"].append("客户图片视觉相似"); candidate["evidence"].append({"type": "IMAGE_SEARCH", "search_id": str(image_search.id), "product_image_id": visual["product_image_id"]})
        ranked = sorted(merged.values(), key=lambda value: value["score"], reverse=True)[:limit]; rows: list[InquiryMatchResultRow] = []
        for rank, candidate in enumerate(ranked, 1):
            product = candidate["product"]; sku = repository.first_sku(session, tenant_id=tenant_id, product_id=product.id); source = repository.first_source(session, tenant_id=tenant_id, product_id=product.id)
            row = InquiryMatchResultRow(tenant_id=tenant_id, inquiry_item_id=item.id, product_id=product.id, sku_id=sku.id if sku else None, supplier_product_id=source.id if source else None, product_version=product.current_version, rank=rank, total_score=candidate["score"], score_breakdown=candidate["breakdown"], reasons=list(dict.fromkeys(candidate["reasons"])), gaps=candidate["gaps"] + ([] if source else ["没有 ACTIVE 供应来源"]), evidence=candidate["evidence"], ranking_version=ranking_version, status="CANDIDATE")
            session.add(row); rows.append(row)
        item.status = "MATCHED" if rows else "NO_MATCH"; session.flush(); output[str(item.id)] = [_match_response(row) for row in rows]
    inquiry.status = "NEEDS_SELECTION"; inquiry.version += 1; session.commit()
    return InquiryMatchResponse(inquiry_id=inquiry.id, status=inquiry.status, ranking_version=ranking_version, candidates=output)


def select_candidate(session: Session, *, tenant_id: UUID, membership_id: UUID, permissions: frozenset[str], item_id: UUID, request: CandidateSelectRequest) -> MatchResultResponse:
    _require(permissions, "inquiry.manage")
    item = repository.get_inquiry_item(session, tenant_id=tenant_id, item_id=item_id); selected = repository.get_match(session, tenant_id=tenant_id, match_id=request.match_result_id)
    if item is None or selected is None or selected.inquiry_item_id != item.id:
        raise ApplicationError("MATCH_RESULT_NOT_FOUND", "Candidate was not found for this inquiry line.", kind="not_found")
    if selected.status != "CANDIDATE":
        raise ApplicationError("MATCH_RESULT_STALE", "Candidate is no longer active; rerun matching and select a current result.", kind="conflict")
    for row in repository.list_candidates(session, tenant_id=tenant_id, item_id=item.id, ranking_version=selected.ranking_version):
        row.status = "SELECTED" if row.id == selected.id else "REJECTED"; row.selected_by_membership_id = membership_id if row.id == selected.id else None; row.selected_at = utcnow() if row.id == selected.id else None
    item.status = "SELECTED"; item.version += 1
    inquiry = repository.get_inquiry(session, tenant_id=tenant_id, inquiry_id=item.inquiry_id); assert inquiry is not None
    items = repository.list_inquiry_items(session, tenant_id=tenant_id, inquiry_id=inquiry.id)
    if all(row.id == item.id or row.status == "SELECTED" for row in items): inquiry.status = "READY_FOR_QUOTE"; inquiry.version += 1
    session.commit(); return _match_response(selected)


def _quote_response(session: Session, quote: QuotationRow, version: QuotationVersionRow, approval: QuotationApprovalRow, permissions: frozenset[str]) -> QuotationResponse:
    show_cost = "product.cost.read" in permissions
    items = [QuotationItemResponse(id=row.id, inquiry_item_id=row.inquiry_item_id, product_id=row.product_id, sku_id=row.sku_id, supplier_product_id=row.supplier_product_id, product_snapshot=row.product_snapshot, source_snapshot=row.source_snapshot, quantity=row.quantity, unit_code=row.unit_code, unit_cost=row.unit_cost if show_cost else None, target_margin_rate=row.target_margin_rate if show_cost else None, unit_price=row.unit_price, line_total=row.line_total, warnings=row.warnings) for row in repository.list_quote_items(session, tenant_id=quote.tenant_id, version_id=version.id)]
    versions = [QuotationVersionSummary(version_number=row.version_number, total_amount=row.total_amount, currency=row.currency, rule_version=row.rule_version, content_hash=row.content_hash, approval_status=version_approval.status, created_at=row.created_at) for row, version_approval in repository.list_quotation_versions(session, tenant_id=quote.tenant_id, quotation_id=quote.id)]
    return QuotationResponse(id=quote.id, quotation_number=quote.quotation_number, inquiry_id=quote.inquiry_id, customer_id=quote.customer_id, currency=quote.currency, status=quote.status, current_version=quote.current_version, total_amount=quote.total_amount, expires_at=quote.expires_at, approval_status=approval.status, version_hash=version.content_hash, items=items, versions=versions, created_at=quote.created_at, updated_at=quote.updated_at)


def create_quotation(session: Session, *, tenant_id: UUID, membership_id: UUID, permissions: frozenset[str], inquiry_id: UUID, request: QuotationCreateRequest) -> QuotationResponse:
    # The service may use supplier cost to calculate a deterministic price,
    # while the response remains redacted for callers without cost access.
    _require(permissions, "quotation.create")
    inquiry = repository.get_inquiry(session, tenant_id=tenant_id, inquiry_id=inquiry_id)
    if inquiry is None: raise ApplicationError("INQUIRY_NOT_FOUND", "Inquiry was not found.", kind="not_found")
    if inquiry.status != "READY_FOR_QUOTE" or inquiry.customer_id is None: raise ApplicationError("INQUIRY_NOT_READY", "Inquiry needs a confirmed customer and one selected candidate per line.", kind="conflict")
    lines = []; total = Decimal("0"); needs_approval = request.target_margin_rate < MIN_MARGIN; now = utcnow()
    for item in repository.list_inquiry_items(session, tenant_id=tenant_id, inquiry_id=inquiry.id):
        match = repository.selected_match(session, tenant_id=tenant_id, item_id=item.id)
        if match is None or item.quantity is None: raise ApplicationError("INQUIRY_SELECTION_MISSING", "Every inquiry line requires a selected candidate.", kind="conflict")
        product = repository.get_product(session, tenant_id=tenant_id, product_id=match.product_id)
        if product is None: raise ApplicationError("PRODUCT_NOT_FOUND", "Selected product is no longer available.", kind="conflict")
        if product.current_version != match.product_version: raise ApplicationError("MATCH_STALE", "Selected product changed after matching; rerun matching before quotation.", kind="conflict")
        source = repository.get_active_source(session, tenant_id=tenant_id, product_id=match.product_id, source_id=match.supplier_product_id) if match.supplier_product_id else repository.first_source(session, tenant_id=tenant_id, product_id=match.product_id)
        if source is None: raise ApplicationError("SUPPLIER_SOURCE_MISSING", "Selected product has no ACTIVE supplier source.", kind="conflict")
        source_id = source.id
        price = repository.current_price(session, tenant_id=tenant_id, source_id=source_id, sku_id=match.sku_id, as_of=now)
        if price is None: raise ApplicationError("CONFIRMED_PRICE_MISSING", "Selected source has no confirmed price.", kind="conflict")
        if price.currency != inquiry.currency: raise ApplicationError("FX_RATE_REQUIRED", "Quotation currency differs from supplier price; an explicit FX snapshot is required.", kind="conflict")
        warnings = []
        valid_to = price.valid_to.replace(tzinfo=UTC) if price.valid_to and price.valid_to.tzinfo is None else price.valid_to
        if valid_to and valid_to < now: warnings.append("供应商价格已过有效期"); needs_approval = True
        unit_price = (price.unit_price / (Decimal("1") - request.target_margin_rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP); line_total = (unit_price * item.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP); total += line_total
        lines.append({"item": item, "match": match, "product": product, "source_id": source_id, "price": price, "unit_price": unit_price, "line_total": line_total, "warnings": warnings})
    status = "NEEDS_APPROVAL" if needs_approval else "CALCULATED"; quote = QuotationRow(tenant_id=tenant_id, quotation_number=f"QT-{now:%Y%m%d}-{uuid4().hex[:8].upper()}", inquiry_id=inquiry.id, customer_id=inquiry.customer_id, currency=inquiry.currency, status=status, current_version=1, total_amount=total, created_by_membership_id=membership_id, expires_at=now + timedelta(days=request.expires_in_days)); session.add(quote); session.flush()
    snapshot = {"quotation_number": quote.quotation_number, "inquiry_id": str(inquiry.id), "currency": quote.currency, "target_margin_rate": str(request.target_margin_rate), "rule_version": RULE_VERSION, "minimum_margin": str(MIN_MARGIN), "items": [{"inquiry_item_id": str(line["item"].id), "product_id": str(line["product"].id), "product_version": line["match"].product_version, "source_id": str(line["source_id"]), "quantity": str(line["item"].quantity), "unit_cost": str(line["price"].unit_price), "unit_price": str(line["unit_price"]), "line_total": str(line["line_total"]), "warnings": line["warnings"]} for line in lines], "total_amount": str(total)}
    content_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest(); version = QuotationVersionRow(tenant_id=tenant_id, quotation_id=quote.id, version_number=1, snapshot=snapshot, content_hash=content_hash, currency=quote.currency, total_amount=total, rule_version=RULE_VERSION, created_by_membership_id=membership_id); session.add(version); session.flush()
    for line in lines:
        session.add(QuotationItemRow(tenant_id=tenant_id, quotation_version_id=version.id, inquiry_item_id=line["item"].id, product_id=line["product"].id, sku_id=line["match"].sku_id, supplier_product_id=line["source_id"], product_snapshot={"id": str(line["product"].id), "code": line["product"].product_code, "name": line["product"].name, "version": line["match"].product_version}, source_snapshot={"supplier_product_id": str(line["source_id"]), "price_id": str(line["price"].id), "currency": line["price"].currency, "valid_from": line["price"].valid_from.isoformat(), "valid_to": line["price"].valid_to.isoformat() if line["price"].valid_to else None}, quantity=line["item"].quantity, unit_code=line["item"].unit_code or "PCS", unit_cost=line["price"].unit_price, target_margin_rate=request.target_margin_rate, unit_price=line["unit_price"], line_total=line["line_total"], warnings=line["warnings"]))
    approval = QuotationApprovalRow(tenant_id=tenant_id, quotation_id=quote.id, quotation_version_id=version.id, requested_by_membership_id=membership_id, status="PENDING"); session.add(approval)
    session.add(OutboxEventRow(tenant_id=tenant_id, decision_id=None, event_type="quotation.created.v1", schema_version=1, aggregate_type="QUOTATION", aggregate_id=str(quote.id), aggregate_version=1, payload={"quotation_id": str(quote.id), "quotation_version_id": str(version.id), "version_hash": content_hash, "status": status, "total_amount": str(total), "currency": quote.currency}, status="PENDING", occurred_at=now, available_at=now))
    inquiry.status = "QUOTED"; inquiry.version += 1; session.commit()
    return _quote_response(session, quote, version, approval, permissions)


def get_quotation(session: Session, *, tenant_id: UUID, permissions: frozenset[str], quotation_id: UUID) -> QuotationResponse:
    _require(permissions, "quotation.view"); group = repository.get_quotation(session, tenant_id=tenant_id, quotation_id=quotation_id)
    if group is None: raise ApplicationError("QUOTATION_NOT_FOUND", "Quotation was not found.", kind="not_found")
    return _quote_response(session, *group, permissions)


def list_quotations(session: Session, *, tenant_id: UUID, permissions: frozenset[str], limit: int) -> list[QuotationSummary]:
    _require(permissions, "quotation.view")
    return [QuotationSummary(id=quote.id, quotation_number=quote.quotation_number, customer_name=customer.company_name, currency=quote.currency, status=quote.status, current_version=quote.current_version, total_amount=quote.total_amount, updated_at=quote.updated_at) for quote, customer in repository.list_quotations(session, tenant_id=tenant_id, limit=limit)]


def decide_quotation(session: Session, *, tenant_id: UUID, membership_id: UUID, permissions: frozenset[str], quotation_id: UUID, request: QuotationDecisionRequest) -> QuotationResponse:
    _require(permissions, "quotation.approve"); group = repository.get_quotation(session, tenant_id=tenant_id, quotation_id=quotation_id)
    if group is None: raise ApplicationError("QUOTATION_NOT_FOUND", "Quotation was not found.", kind="not_found")
    quote, version, approval = group
    if approval.status != "PENDING": raise ApplicationError("QUOTATION_ALREADY_DECIDED", "This quotation version already has a decision.", kind="conflict")
    decided_at = utcnow(); approval.status = request.decision; approval.reason = request.reason; approval.decided_by_membership_id = membership_id; approval.decided_at = decided_at; quote.status = request.decision; quote.approved_by_membership_id = membership_id if request.decision == "APPROVED" else None; quote.approved_at = decided_at if request.decision == "APPROVED" else None
    session.add(OutboxEventRow(tenant_id=tenant_id, decision_id=None, event_type=f"quotation.{request.decision.lower()}.v1", schema_version=1, aggregate_type="QUOTATION", aggregate_id=str(quote.id), aggregate_version=quote.current_version, payload={"quotation_id": str(quote.id), "quotation_version_id": str(version.id), "version_hash": version.content_hash, "decision": request.decision, "decided_by_membership_id": str(membership_id)}, status="PENDING", occurred_at=decided_at, available_at=decided_at))
    session.commit()
    return _quote_response(session, quote, version, approval, permissions)


def revise_quotation(session: Session, *, tenant_id: UUID, membership_id: UUID, permissions: frozenset[str], quotation_id: UUID, request: QuotationRevisionRequest) -> QuotationResponse:
    _require(permissions, "quotation.create")
    group = repository.get_quotation_for_update(session, tenant_id=tenant_id, quotation_id=quotation_id)
    if group is None:
        raise ApplicationError("QUOTATION_NOT_FOUND", "Quotation was not found.", kind="not_found")
    quote, current_version, _current_approval = group
    if quote.current_version != request.expected_version:
        raise ApplicationError("QUOTATION_VERSION_CONFLICT", "Quotation changed after it was opened; reload the latest version.", kind="conflict")
    current_items = repository.list_quote_items(session, tenant_id=tenant_id, version_id=current_version.id)
    changes = {item.item_id: item for item in request.items}
    unknown_ids = set(changes) - {item.id for item in current_items}
    if unknown_ids:
        raise ApplicationError("QUOTATION_ITEM_NOT_FOUND", "One or more quotation items are not part of the current version.", kind="not_found")
    if len(changes) != len(current_items):
        raise ApplicationError("QUOTATION_ITEMS_INCOMPLETE", "Every current quotation item must be included in a revision.", kind="conflict")

    total = Decimal("0")
    next_number = quote.current_version + 1
    revised_lines: list[dict[str, object]] = []
    needs_approval = False
    for current in current_items:
        change = changes[current.id]
        margin = change.target_margin_rate
        quantity = change.quantity
        unit_price = (current.unit_cost / (Decimal("1") - margin)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line_total = (unit_price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        warnings = [warning for warning in current.warnings if "目标毛利低于" not in warning]
        if margin < MIN_MARGIN:
            warnings.append("目标毛利低于公司底线，必须重新审批")
            needs_approval = True
        total += line_total
        revised_lines.append({"current": current, "quantity": quantity, "margin": margin, "unit_price": unit_price, "line_total": line_total, "warnings": warnings})

    now = utcnow()
    snapshot = {
        "quotation_number": quote.quotation_number,
        "inquiry_id": str(quote.inquiry_id),
        "currency": quote.currency,
        "version_number": next_number,
        "previous_version_hash": current_version.content_hash,
        "change_reason": request.change_reason,
        "rule_version": RULE_VERSION,
        "minimum_margin": str(MIN_MARGIN),
        "items": [{"inquiry_item_id": str(line["current"].inquiry_item_id), "product_id": str(line["current"].product_id), "source_id": str(line["current"].supplier_product_id), "quantity": str(line["quantity"]), "unit_cost": str(line["current"].unit_cost), "target_margin_rate": str(line["margin"]), "unit_price": str(line["unit_price"]), "line_total": str(line["line_total"]), "warnings": line["warnings"]} for line in revised_lines],
        "total_amount": str(total),
    }
    content_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    version = QuotationVersionRow(tenant_id=tenant_id, quotation_id=quote.id, version_number=next_number, snapshot=snapshot, content_hash=content_hash, currency=quote.currency, total_amount=total, rule_version=RULE_VERSION, created_by_membership_id=membership_id)
    session.add(version)
    session.flush()
    for line in revised_lines:
        current = line["current"]
        session.add(QuotationItemRow(tenant_id=tenant_id, quotation_version_id=version.id, inquiry_item_id=current.inquiry_item_id, product_id=current.product_id, sku_id=current.sku_id, supplier_product_id=current.supplier_product_id, product_snapshot=current.product_snapshot, source_snapshot=current.source_snapshot, quantity=line["quantity"], unit_code=current.unit_code, unit_cost=current.unit_cost, target_margin_rate=line["margin"], unit_price=line["unit_price"], line_total=line["line_total"], warnings=line["warnings"]))
    approval = QuotationApprovalRow(tenant_id=tenant_id, quotation_id=quote.id, quotation_version_id=version.id, requested_by_membership_id=membership_id, status="PENDING")
    session.add(approval)
    quote.current_version = next_number
    quote.total_amount = total
    quote.status = "NEEDS_APPROVAL" if needs_approval else "CALCULATED"
    quote.approved_by_membership_id = None
    quote.approved_at = None
    if request.expires_in_days is not None:
        quote.expires_at = now + timedelta(days=request.expires_in_days)
    session.add(OutboxEventRow(tenant_id=tenant_id, decision_id=None, event_type="quotation.revised.v1", schema_version=1, aggregate_type="QUOTATION", aggregate_id=str(quote.id), aggregate_version=next_number, payload={"quotation_id": str(quote.id), "quotation_version_id": str(version.id), "version_hash": content_hash, "previous_version_hash": current_version.content_hash, "change_reason": request.change_reason, "status": quote.status, "total_amount": str(total), "currency": quote.currency}, status="PENDING", occurred_at=now, available_at=now))
    session.commit()
    return _quote_response(session, quote, version, approval, permissions)
