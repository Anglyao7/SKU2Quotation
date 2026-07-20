import atexit
import hashlib
import io
import os
import shutil
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Response
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError


TEST_RUNTIME = Path(tempfile.mkdtemp(prefix="mercator-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(TEST_RUNTIME / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(TEST_RUNTIME / "uploads")
os.environ["APP_ENV"] = "test"
os.environ["AUTH_PROFILE"] = "local_fake"
os.environ["AUTH_TEST_BYPASS"] = "true"

from app.main import app
from app.domain.errors import ApplicationError
from app.routers.auth import _set_refresh_cookie
from app.database import API_ROOT, SessionLocal, engine
from app.identity_models import (
    AuthRefreshTokenRow,
    AuthSessionRow,
    MembershipRoleRow,
    MembershipRow,
    OrganizationRow,
    PermissionRow,
    RolePermissionRow,
    RoleRow,
    TenantRow,
    UserRow,
)
from app.ai_data_models import AIProviderRouteRow, AISourceEvidenceRow, AITaskRow
from app.knowledge_embedding_models import EmbeddingRow, KnowledgeChunkRow, KnowledgeDocumentRow
from app.image_intelligence_models import ImageEmbeddingRow, ImageSearchRow, VisionObservationRow
from app.db_models import ImportJobRow, ReviewItemRow, SourceFileRow, SupplierRow
from app.file_security_models import MediaObjectRow, WorkerJobRow
from app.product_center_models import (
    AttributeDefinitionRow,
    ProductAuditEventRow,
    SkuRow,
    SupplierPriceRow,
)
from app.product_intelligence_models import (
    AIRunRow,
    AITaskStepRow,
    InboxEventRow,
    OutboxEventRow,
    ProductCandidateDecisionRow,
    ProductFieldCandidateRow,
)
from app.product_supplier_models import (
    ProductAttributeRow,
    ProductCategoryRow,
    ProductImageRow,
    ProductRow,
    ProductVersionRow,
    SupplierProductRow,
    SupplierScoreRow,
)
from app.models import PriceCalculationRequest
from app.saas_seed import (
    DEFAULT_MEMBERSHIP_ID,
    DEFAULT_ORGANIZATION_ID,
    DEFAULT_OWNER_USER_ID,
    DEFAULT_TENANT_ID,
    PERMISSION_SEEDS,
    seed_saas_foundation,
)
from app.services.file_detection import OLE_SIGNATURE, detect_file_path, detect_file_type
from app.services.embedding import validate_vectors
from app.services.hybrid_search import hybrid_product_search
from app.services.knowledge import project_product_knowledge
from app.services.parsers import parse_document
from app.services.pricing import calculate_price
from app.services.product_intelligence.fake_parser import FakeProductParserAdapter
from app.services.product_intelligence.native_parser import NativeSupplierFileParserAdapter
from app.services.product_intelligence.workflow import (
    ProductWorkflowNotFound,
    run_product_draft_workflow,
)
from app.services.product_intelligence.adoption import (
    ProductAdoptionError,
    approve_candidate_group,
    dispatch_product_committed_event,
    reject_candidate_group,
)
from app.services.product_intelligence.normalization import normalize_product_field
from app.services.rbac import has_permission, list_permissions
from app.services.auth.tokens import REFRESH_COOKIE_NAME, hash_secret
from app.model_mixins import mark_deleted, restore_deleted
from app.adapters.file_scanner import (
    DeterministicDevelopmentScanner,
    get_file_scanner,
)
from app.adapters.object_storage import get_object_storage
from app.adapters.image_intelligence import get_image_intelligence_provider
from app.adapters.outbox_publisher import InMemoryOutboxPublisher, get_outbox_publisher
from app.services.outbox_consumer import consume_product_committed_message
from app.workers.file_processing import process_file_worker_job
from app.workers.outbox_relay import relay_one_outbox_event
from app.use_cases.product_center import list_products as list_authoritative_products
from app.use_cases.product_center import upsert_public_offer as upsert_public_offer_use_case
from app.product_center_schemas import PublicCatalogOfferUpsertRequest
from app.use_cases.workspace import create_supplier as create_supplier_use_case
from app.workspace_schemas import SupplierCreateRequest
from app.trade_flow_models import InquiryMatchResultRow, InquiryRow, QuotationApprovalRow, QuotationItemRow, QuotationRow, QuotationVersionRow
from app.public_catalog_models import (
    PublicCatalogOfferRow,
    PublicQuoteDownloadTokenRow,
    PublicQuoteDraftItemRow,
    PublicQuoteDraftRow,
)


client = TestClient(app)


def _create_pending_product_event(tmp_path: Path, *, suffix: str) -> UUID:
    workbook_path = tmp_path / f"outbox-{suffix}.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Products"
    sheet.append(["Product Name", "Item No", "Material", "MOQ"])
    sheet.append([f"Outbox Product {suffix}", f"OB-{suffix}", "TPR", 100])
    workbook.save(workbook_path)
    source_id = f"SRC-{uuid4().hex[:12].upper()}"
    job_id = f"JOB-{uuid4().hex[:12].upper()}"
    with SessionLocal() as session:
        supplier = session.scalar(
            select(SupplierRow).where(
                SupplierRow.tenant_id == DEFAULT_TENANT_ID,
                SupplierRow.status == "ACTIVE",
            )
        )
        assert supplier is not None
        session.add(
            SourceFileRow(
                id=source_id,
                tenant_id=DEFAULT_TENANT_ID,
                original_filename=workbook_path.name,
                stored_filename=workbook_path.name,
                local_path=str(workbook_path),
                sha256=hashlib.sha256(workbook_path.read_bytes()).hexdigest(),
                byte_size=workbook_path.stat().st_size,
                extension=".xlsx",
                detected_type="OOXML / XLSX",
                extension_matches=True,
                parser="openpyxl",
                security_status="LEGACY_ACCEPTED",
            )
        )
        session.add(
            ImportJobRow(
                id=job_id,
                tenant_id=DEFAULT_TENANT_ID,
                source_file_id=source_id,
                supplier_id=supplier.id,
                supplier_name=supplier.name,
                source_type="SUPPLIER_CATALOG",
                status="needs_review",
                progress=100,
                products_count=1,
            )
        )
        session.commit()
        workflow = run_product_draft_workflow(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            source_file_id=source_id,
            parser=NativeSupplierFileParserAdapter(),
            idempotency_context=f"supplier:{supplier.id}:{suffix}",
        )
        session.commit()
        candidates = session.scalars(
            select(ProductFieldCandidateRow).where(
                ProductFieldCandidateRow.tenant_id == DEFAULT_TENANT_ID,
                ProductFieldCandidateRow.ai_task_id == workflow.task_id,
            )
        ).all()
        assert candidates
        group_key = candidates[0].candidate_group_key
        values = {
            candidate.field_key: candidate.raw_value
            for candidate in candidates
            if candidate.candidate_group_key == group_key
        }
        result = approve_candidate_group(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            task_id=workflow.task_id,
            candidate_group_key=group_key,
            reviewer_membership_id=DEFAULT_MEMBERSHIP_ID,
            idempotency_key=f"outbox-approve-{uuid4()}",
            confirmed_values=values,
            activate=True,
            product_code=f"ATC-OB-{uuid4().hex[:10].upper()}",
            change_reason="ACG-008 relay verification",
        )
        session.commit()
        return result.outbox_event_id


def cleanup_test_runtime() -> None:
    engine.dispose()
    shutil.rmtree(TEST_RUNTIME, ignore_errors=True)


atexit.register(cleanup_test_runtime)


def test_health() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "local_persistence"
    assert response.json()["config_version"] == "local"
    assert client.get("/api/v1/health/live").status_code == 200

    ready = client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["dependencies"]["database"]["status"] == "ready"


def test_readiness_fails_closed_on_migration_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATC_MIGRATION_HEAD", "20990101_9999")
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["dependencies"]["database"]["reason"] == "MIGRATION_HEAD_MISMATCH"


def test_trusted_auth_session_membership_refresh_and_logout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_TEST_BYPASS", "false")
    assert client.get("/api/v1/suppliers").status_code == 401

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "provider": "local_fake",
            "authorization_code": f"fake:{DEFAULT_OWNER_USER_ID}",
            "code_verifier": "A" * 43,
            "redirect_uri": "http://127.0.0.1:5173/login/callback",
            "device_label": "pytest-browser",
        },
    )
    assert login_response.status_code == 200, login_response.text
    token_data = login_response.json()["data"]
    access_token = token_data["access_token"]
    csrf_token = token_data["csrf_token"]
    raw_refresh = login_response.cookies.get(REFRESH_COOKIE_NAME)
    assert raw_refresh
    assert "httponly" in login_response.headers["set-cookie"].lower()
    assert raw_refresh not in login_response.text

    with SessionLocal() as session:
        auth_session = session.get(AuthSessionRow, UUID(token_data["session_id"]))
        assert auth_session is not None
        assert auth_session.active_membership_id == DEFAULT_MEMBERSHIP_ID
        stored_refresh = session.scalar(
            select(AuthRefreshTokenRow).where(
                AuthRefreshTokenRow.auth_session_id == auth_session.id,
                AuthRefreshTokenRow.sequence_number == 0,
            )
        )
        assert stored_refresh is not None
        assert stored_refresh.token_hash == hash_secret(raw_refresh)
        assert stored_refresh.token_hash != raw_refresh

    bearer_headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Tenant-ID": str(uuid4()),
    }
    me_response = client.get("/api/v1/me", headers=bearer_headers)
    assert me_response.status_code == 200, me_response.text
    assert me_response.json()["context"]["tenant_id"] == str(DEFAULT_TENANT_ID)
    assert me_response.json()["context"]["tenant_slug"] == "demo"
    assert me_response.json()["user"]["is_platform_admin"] is True
    permissions_response = client.get(
        "/api/v1/me/permissions", headers=bearer_headers
    )
    assert permissions_response.status_code == 200
    assert "product.view" in permissions_response.json()["permissions"]
    memberships_response = client.get(
        "/api/v1/auth/memberships", headers=bearer_headers
    )
    assert memberships_response.status_code == 200
    assert memberships_response.json() == [
        {
            "id": str(DEFAULT_MEMBERSHIP_ID),
            "tenant_id": str(DEFAULT_TENANT_ID),
            "tenant_name": "Local Demo Company",
            "tenant_slug": "demo",
            "status": "active",
        }
    ]

    with SessionLocal() as session:
        membership = session.get(MembershipRow, DEFAULT_MEMBERSHIP_ID)
        assert membership is not None
        membership.status = "suspended"
        session.commit()
    suspended_response = client.get("/api/v1/me", headers=bearer_headers)
    assert suspended_response.status_code == 403
    with SessionLocal() as session:
        membership = session.get(MembershipRow, DEFAULT_MEMBERSHIP_ID)
        assert membership is not None
        membership.status = "active"
        session.commit()

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert refresh_response.status_code == 200, refresh_response.text
    rotated_data = refresh_response.json()["data"]

    with TestClient(app) as replay_client:
        replay_client.cookies.set(REFRESH_COOKIE_NAME, raw_refresh, path="/api/v1/auth")
        replay_response = replay_client.post(
            "/api/v1/auth/refresh",
            headers={"X-CSRF-Token": csrf_token},
        )
    assert replay_response.status_code == 401
    assert replay_response.json()["detail"]["code"] == "AUTH_REFRESH_REUSE_DETECTED"
    assert client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {rotated_data['access_token']}"},
    ).status_code == 401

    second_login = client.post(
        "/api/v1/auth/login",
        json={
            "provider": "local_fake",
            "authorization_code": f"fake:{DEFAULT_OWNER_USER_ID}",
            "code_verifier": "B" * 43,
            "redirect_uri": "http://localhost:5173/login/callback",
        },
    )
    assert second_login.status_code == 200
    second_access = second_login.json()["data"]["access_token"]
    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {second_access}"},
    )
    assert logout_response.status_code == 204
    assert client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {second_access}"},
    ).status_code == 401


def test_platform_admin_manages_tenant_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = f"merchant-{uuid4().hex[:10]}"
    created = client.post(
        "/api/admin/tenants",
        json={
            "name": "Platform Managed Merchant",
            "slug": slug,
            "contact_email": "ops@merchant.example",
            "active": True,
        },
    )
    assert created.status_code == 201, created.text
    tenant = created.json()
    tenant_id = tenant["id"]
    assert tenant["slug"] == slug
    assert tenant["status"] == "active"
    assert tenant["active"] is True
    assert tenant["contact_email"] == "ops@merchant.example"
    assert tenant["sku_count"] == 0 and tenant["quote_count"] == 0
    assert client.get(f"/api/store/{slug}").status_code == 200

    merchant_user_id = uuid4()
    with SessionLocal() as session:
        session.add(
            UserRow(
                id=merchant_user_id,
                email_normalized=f"{merchant_user_id.hex}@suspended-tenant.test",
                display_name="Suspended Tenant Member",
                identity_provider="local-bootstrap",
                identity_subject=str(merchant_user_id),
                status="active",
            )
        )
        session.add(
            MembershipRow(
                tenant_id=UUID(tenant_id),
                user_id=merchant_user_id,
                status="active",
            )
        )
        session.commit()

    duplicate = client.post(
        "/api/admin/tenants",
        json={"name": "Duplicate", "slug": slug},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "TENANT_SLUG_EXISTS"

    suspended = client.patch(
        f"/api/admin/tenants/{tenant_id}",
        json={"name": "Suspended Merchant", "active": False},
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"
    assert suspended.json()["active"] is False
    assert client.get(f"/api/store/{slug}").status_code == 404
    monkeypatch.setenv("AUTH_TEST_BYPASS", "false")
    with TestClient(app) as suspended_client:
        suspended_login = suspended_client.post(
            "/api/v1/auth/login",
            json={
                "provider": "local_fake",
                "authorization_code": f"fake:{merchant_user_id}",
                "code_verifier": "S" * 43,
                "redirect_uri": "http://127.0.0.1:5173/login/callback",
            },
        )
    assert suspended_login.status_code == 403
    assert suspended_login.json()["detail"]["code"] == "AUTH_MEMBERSHIP_REQUIRED"
    monkeypatch.setenv("AUTH_TEST_BYPASS", "true")

    reactivated = client.patch(
        f"/api/admin/tenants/{tenant_id}",
        json={"contact_email": "new@merchant.example", "active": True},
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["status"] == "active"
    assert reactivated.json()["contact_email"] == "new@merchant.example"
    assert client.get(f"/api/store/{slug}").status_code == 200

    rows = client.get("/api/admin/tenants")
    assert rows.status_code == 200, rows.text
    assert tenant_id in {row["id"] for row in rows.json()}

    current_tenant_guard = client.patch(
        f"/api/admin/tenants/{DEFAULT_TENANT_ID}",
        json={"active": False},
    )
    assert current_tenant_guard.status_code == 409
    assert current_tenant_guard.json()["detail"]["code"] == "ACTIVE_TENANT_SUSPENSION_FORBIDDEN"


def test_platform_admin_routes_reject_regular_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    membership_id = uuid4()
    with SessionLocal() as session:
        session.add(
            UserRow(
                id=user_id,
                email_normalized=f"{user_id.hex}@platform-admin.test",
                display_name="Regular Tenant Member",
                identity_provider="local-bootstrap",
                identity_subject=str(user_id),
                status="active",
                is_platform_admin=False,
            )
        )
        session.add(
            MembershipRow(
                id=membership_id,
                tenant_id=DEFAULT_TENANT_ID,
                user_id=user_id,
                status="active",
            )
        )
        session.commit()

    monkeypatch.setenv("AUTH_TEST_BYPASS", "false")
    with TestClient(app) as regular_client:
        login_response = regular_client.post(
            "/api/v1/auth/login",
            json={
                "provider": "local_fake",
                "authorization_code": f"fake:{user_id}",
                "code_verifier": "R" * 43,
                "redirect_uri": "http://127.0.0.1:5173/login/callback",
            },
        )
        assert login_response.status_code == 200, login_response.text
        token = login_response.json()["data"]["access_token"]
        denied = regular_client.get(
            "/api/admin/tenants",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "PLATFORM_ADMIN_REQUIRED"


def test_refresh_cookie_is_secure_in_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    response = Response()
    _set_refresh_cookie(response, "opaque-refresh-token")
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie


def test_multi_tenant_session_requires_server_validated_tenant_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_TEST_BYPASS", "false")
    organization_id = uuid4()
    tenant_id = uuid4()
    membership_id = uuid4()
    with SessionLocal() as session:
        session.add(
            OrganizationRow(
                id=organization_id,
                code=f"AUTH-{str(organization_id)[:8]}",
                name="Authentication Tenant Switch Test",
            )
        )
        session.add(
            TenantRow(
                id=tenant_id,
                organization_id=organization_id,
                slug=f"auth-{str(tenant_id)[:8]}",
                name="Tenant B",
            )
        )
        session.add(
            MembershipRow(
                id=membership_id,
                tenant_id=tenant_id,
                user_id=DEFAULT_OWNER_USER_ID,
                status="active",
            )
        )
        session.commit()

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "provider": "local_fake",
            "authorization_code": f"fake:{DEFAULT_OWNER_USER_ID}",
            "code_verifier": "C" * 43,
            "redirect_uri": "http://127.0.0.1:5173/login/callback",
        },
    )
    assert login_response.status_code == 200
    login_data = login_response.json()["data"]
    assert login_data["requires_tenant_selection"] is True
    assert login_data["context"]["tenant_id"] is None
    access = login_data["access_token"]
    csrf = login_data["csrf_token"]
    auth_header = {"Authorization": f"Bearer {access}"}
    membership_options = client.get(
        "/api/v1/auth/memberships", headers=auth_header
    )
    assert membership_options.status_code == 200
    assert {row["id"] for row in membership_options.json()} == {
        str(DEFAULT_MEMBERSHIP_ID),
        str(membership_id),
    }
    assert client.get("/api/v1/me", headers=auth_header).status_code == 403

    invalid_switch = client.post(
        "/api/v1/auth/tenant-context",
        json={"membership_id": str(uuid4())},
        headers={**auth_header, "X-CSRF-Token": csrf},
    )
    assert invalid_switch.status_code == 403

    switch_response = client.post(
        "/api/v1/auth/tenant-context",
        json={"membership_id": str(membership_id)},
        headers={**auth_header, "X-CSRF-Token": csrf},
    )
    assert switch_response.status_code == 200, switch_response.text
    switched = switch_response.json()["data"]
    assert switched["context"]["tenant_id"] == str(tenant_id)
    me_response = client.get(
        "/api/v1/me",
        headers={
            "Authorization": f"Bearer {switched['access_token']}",
            "X-Tenant-ID": str(DEFAULT_TENANT_ID),
        },
    )
    assert me_response.status_code == 200, me_response.text
    assert me_response.json()["context"]["tenant_id"] == str(tenant_id)


def test_phase4a1a_schema_contains_only_approved_product_intelligence_tables() -> None:
    tables = set(inspect(engine).get_table_names())
    assert {
        "organizations",
        "tenants",
        "users",
        "memberships",
        "roles",
        "permissions",
        "role_permissions",
        "membership_roles",
    }.issubset(tables)
    assert {
        "products",
        "product_images",
        "product_categories",
        "product_attributes",
        "suppliers",
        "supplier_products",
        "supplier_score",
    }.issubset(tables)
    assert {"ai_tasks", "ai_provider_routes", "ai_source_evidence"}.issubset(tables)
    assert {"knowledge_documents", "knowledge_chunks", "embeddings"}.issubset(tables)
    assert {"ai_runs", "ai_task_steps", "product_field_candidates"}.issubset(tables)
    assert {
        "product_candidate_decisions",
        "product_versions",
        "outbox_events",
        "tenant_public_profiles",
        "public_catalog_offers",
        "public_quote_drafts",
        "public_quote_draft_items",
        "public_quote_download_tokens",
    }.issubset(tables)
    assert {"auth_sessions", "auth_refresh_tokens", "media_objects", "worker_jobs"}.issubset(
        tables
    )
    assert {
        "inbox_events",
        "skus",
        "attribute_definitions",
        "supplier_prices",
        "product_audit_events",
        "vision_observations",
        "image_embeddings",
        "image_searches",
        "customers",
        "inquiries",
        "inquiry_items",
        "inquiry_match_results",
        "quotations",
        "quotation_versions",
        "quotation_items",
        "quotation_approvals",
    }.issubset(tables)
    assert {
        "ai_agents",
        "agents",
        "knowledge_base",
        "knowledge_bases",
        "vector_indexes",
        "orders",
    }.isdisjoint(tables)
    assert {"suppliers", "source_files", "import_jobs", "review_items"}.issubset(tables)


def test_phase4a1a_tables_are_tenant_scoped_candidate_only_and_product_detached() -> None:
    database_inspector = inspect(engine)
    for table_name in (
        "ai_runs",
        "ai_task_steps",
        "product_field_candidates",
        "product_candidate_decisions",
        "product_versions",
        "outbox_events",
        "tenant_public_profiles",
        "public_catalog_offers",
        "public_quote_drafts",
        "public_quote_draft_items",
        "public_quote_download_tokens",
    ):
        columns = {column["name"] for column in database_inspector.get_columns(table_name)}
        assert {"tenant_id", "created_at", "updated_at", "deleted_at"}.issubset(columns)

    candidate_columns = {
        column["name"]
        for column in database_inspector.get_columns("product_field_candidates")
    }
    assert {
        "ai_task_id",
        "ai_run_id",
        "source_evidence_id",
        "raw_value",
        "normalized_value",
        "review_status",
    }.issubset(candidate_columns)
    assert {"product_id", "embedding", "vector", "published_at"}.isdisjoint(
        candidate_columns
    )
    product_columns = {
        column["name"] for column in database_inspector.get_columns("products")
    }
    assert {"ai_task_id", "candidate_id", "candidate_payload"}.isdisjoint(product_columns)
    run_checks = {
        item["sqltext"] for item in database_inspector.get_check_constraints("ai_runs")
    }
    assert any("NATIVE" in expression for expression in run_checks if expression)


def test_phase3a_tables_are_tenant_scoped_and_minimize_sensitive_payloads() -> None:
    database_inspector = inspect(engine)
    for table_name in ("ai_tasks", "ai_provider_routes", "ai_source_evidence"):
        columns = {column["name"] for column in database_inspector.get_columns(table_name)}
        assert {"tenant_id", "created_at", "updated_at", "deleted_at"}.issubset(columns)

    task_columns = {column["name"] for column in database_inspector.get_columns("ai_tasks")}
    route_columns = {
        column["name"] for column in database_inspector.get_columns("ai_provider_routes")
    }
    evidence_columns = {
        column["name"] for column in database_inspector.get_columns("ai_source_evidence")
    }
    assert {"input_ref", "input_hash", "route_snapshot"}.issubset(task_columns)
    assert {"input", "output", "prompt", "embedding", "vector"}.isdisjoint(task_columns)
    assert "credential_secret_ref" in route_columns
    assert {"api_key", "credential_value", "secret_value"}.isdisjoint(route_columns)
    assert {"raw_value_ref", "raw_value_hash", "evidence_hash"}.issubset(evidence_columns)
    assert {"raw_value", "embedding", "vector"}.isdisjoint(evidence_columns)


def test_phase3b_tables_are_tenant_scoped_traceable_and_soft_deletable() -> None:
    database_inspector = inspect(engine)
    for table_name in ("knowledge_documents", "knowledge_chunks", "embeddings"):
        columns = {column["name"] for column in database_inspector.get_columns(table_name)}
        assert {"tenant_id", "created_at", "updated_at", "deleted_at"}.issubset(columns)

    document_columns = {
        column["name"] for column in database_inspector.get_columns("knowledge_documents")
    }
    chunk_columns = {
        column["name"] for column in database_inspector.get_columns("knowledge_chunks")
    }
    embedding_columns = {
        column["name"] for column in database_inspector.get_columns("embeddings")
    }
    assert {
        "source_entity_type",
        "source_entity_id",
        "source_version",
        "schema_version",
        "field_policy_version",
        "content_hash",
    }.issubset(document_columns)
    assert {"document_id", "chunk_type", "content", "content_hash", "metadata"}.issubset(
        chunk_columns
    )
    assert {
        "entity_type",
        "entity_id",
        "model_provider",
        "model_name",
        "model_version",
        "dimensions",
        "embedding",
    }.issubset(embedding_columns)
    assert {"prompt", "completion", "agent_state", "purchase_price", "profit"}.isdisjoint(
        document_columns | chunk_columns | embedding_columns
    )


def test_phase1_5_all_saas_core_tables_have_lifecycle_timestamps() -> None:
    table_names = (
        "organizations",
        "tenants",
        "users",
        "memberships",
        "roles",
        "permissions",
        "role_permissions",
        "membership_roles",
    )
    database_inspector = inspect(engine)
    for table_name in table_names:
        columns = {column["name"] for column in database_inspector.get_columns(table_name)}
        assert {"created_at", "updated_at", "deleted_at"}.issubset(columns)


def test_phase2_core_and_legacy_import_tables_have_lifecycle_and_tenant_columns() -> None:
    table_names = (
        "product_categories",
        "products",
        "product_images",
        "product_attributes",
        "suppliers",
        "supplier_products",
        "supplier_score",
        "source_files",
        "import_jobs",
        "review_items",
    )
    database_inspector = inspect(engine)
    for table_name in table_names:
        columns = {column["name"] for column in database_inspector.get_columns(table_name)}
        assert {"tenant_id", "created_at", "updated_at", "deleted_at"}.issubset(columns)

    product_columns = {column["name"] for column in database_inspector.get_columns("products")}
    image_columns = {column["name"] for column in database_inspector.get_columns("product_images")}
    assert "supplier_id" not in product_columns
    assert "embedding" not in image_columns
    assert "vector" not in image_columns
    supplier_checks = {
        item["name"] for item in database_inspector.get_check_constraints("suppliers")
    }
    image_checks = {
        item["name"] for item in database_inspector.get_check_constraints("product_images")
    }
    assert any(name and name.endswith("status_allowed") for name in supplier_checks)
    assert any(name and name.endswith("risk_level_allowed") for name in supplier_checks)
    assert any(name and name.endswith("image_role_allowed") for name in image_checks)


def test_phase1_seed_is_idempotent_and_owner_has_all_permissions() -> None:
    with SessionLocal() as session:
        before = session.scalar(select(func.count()).select_from(PermissionRow))
        seed_saas_foundation(session)
        after = session.scalar(select(func.count()).select_from(PermissionRow))
        permissions = list_permissions(
            session, tenant_id=DEFAULT_TENANT_ID, user_id=DEFAULT_OWNER_USER_ID
        )

    assert before == after == len(PERMISSION_SEEDS)
    assert permissions == frozenset(seed.code for seed in PERMISSION_SEEDS)
    assert "system.role_manage" in permissions


def test_rbac_denies_cross_tenant_permissions_and_database_rejects_cross_tenant_assignment() -> None:
    organization_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    membership_id = uuid4()
    role_id = uuid4()

    with SessionLocal() as session:
        permission = session.scalar(select(PermissionRow).where(PermissionRow.code == "product.view"))
        owner_role = session.scalar(
            select(RoleRow).where(RoleRow.tenant_id == DEFAULT_TENANT_ID, RoleRow.code == "OWNER")
        )
        assert permission is not None and owner_role is not None
        session.add_all([
            OrganizationRow(id=organization_id, code=f"ORG-{organization_id.hex[:8]}", name="Tenant B Org"),
            UserRow(
                id=user_id,
                email_normalized=f"{user_id.hex}@example.test",
                display_name="Tenant B User",
                identity_provider="test",
                identity_subject=str(user_id),
                status="active",
            ),
        ])
        session.flush()
        session.add(TenantRow(
            id=tenant_id,
            organization_id=organization_id,
            slug=f"tenant-{tenant_id.hex[:8]}",
            name="Tenant B",
        ))
        session.flush()
        session.add_all([
            MembershipRow(
                id=membership_id,
                tenant_id=tenant_id,
                user_id=user_id,
                status="active",
            ),
            RoleRow(
                id=role_id,
                tenant_id=tenant_id,
                code="VIEWER",
                name="Viewer",
                status="active",
            ),
        ])
        session.flush()
        session.add_all([
            RolePermissionRow(
                tenant_id=tenant_id,
                role_id=role_id,
                permission_id=permission.id,
            ),
            MembershipRoleRow(
                tenant_id=tenant_id,
                membership_id=membership_id,
                role_id=role_id,
                assigned_by_user_id=user_id,
            ),
        ])
        session.commit()

        assert has_permission(
            session, tenant_id=tenant_id, user_id=user_id, permission_code="product.view"
        )
        assert not has_permission(
            session, tenant_id=DEFAULT_TENANT_ID, user_id=user_id, permission_code="product.view"
        )

        session.add(MembershipRoleRow(
            tenant_id=DEFAULT_TENANT_ID,
            membership_id=membership_id,
            role_id=owner_role.id,
            assigned_by_user_id=DEFAULT_OWNER_USER_ID,
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

def test_custom_role_and_soft_delete_contract() -> None:
    user_id = uuid4()
    membership_id = uuid4()
    role_id = uuid4()

    with SessionLocal() as session:
        permission = session.scalar(
            select(PermissionRow).where(PermissionRow.code == "quotation.approve")
        )
        assert permission is not None
        session.add(UserRow(
            id=user_id,
            email_normalized=f"{user_id.hex}@custom-role.test",
            display_name="Custom Role User",
            identity_provider="test",
            identity_subject=str(user_id),
            status="active",
        ))
        session.add(MembershipRow(
            id=membership_id,
            tenant_id=DEFAULT_TENANT_ID,
            user_id=user_id,
            status="active",
        ))
        session.add(RoleRow(
            id=role_id,
            tenant_id=DEFAULT_TENANT_ID,
            code=f"CUSTOM_{role_id.hex[:8].upper()}",
            name="Custom Approver",
            is_system=False,
            status="active",
        ))
        session.flush()
        session.add_all([
            RolePermissionRow(
                tenant_id=DEFAULT_TENANT_ID,
                role_id=role_id,
                permission_id=permission.id,
            ),
            MembershipRoleRow(
                tenant_id=DEFAULT_TENANT_ID,
                membership_id=membership_id,
                role_id=role_id,
                assigned_by_user_id=DEFAULT_OWNER_USER_ID,
            ),
        ])
        session.commit()
        assert has_permission(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            user_id=user_id,
            permission_code="quotation.approve",
        )

        role = session.get(RoleRow, role_id)
        assert role is not None
        mark_deleted(role)
        session.commit()

    with SessionLocal() as session:
        assert session.get(RoleRow, role_id) is None
        deleted_role = session.get(
            RoleRow,
            role_id,
            execution_options={"include_deleted": True},
        )
        assert deleted_role is not None and deleted_role.deleted_at is not None
        assert not has_permission(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            user_id=user_id,
            permission_code="quotation.approve",
        )
        restore_deleted(deleted_role)
        session.commit()
        assert has_permission(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            user_id=user_id,
            permission_code="quotation.approve",
        )


def test_phase2_product_supports_typed_attributes_images_and_multiple_suppliers() -> None:
    category_id = uuid4()
    product_id = uuid4()
    with SessionLocal() as session:
        session.add(ProductCategoryRow(
            id=category_id,
            tenant_id=DEFAULT_TENANT_ID,
            code=f"PET-{category_id.hex[:8]}",
            name="Pet Supplies",
        ))
        session.add(ProductRow(
            id=product_id,
            tenant_id=DEFAULT_TENANT_ID,
            product_code=f"PROD-{product_id.hex[:8]}",
            name="Test Pet Bowl",
            category_id=category_id,
            default_unit="piece",
            status="ACTIVE",
        ))
        session.flush()
        session.add_all([
            ProductAttributeRow(
                tenant_id=DEFAULT_TENANT_ID,
                product_id=product_id,
                attribute_key="weight",
                value_number=Decimal("200"),
                unit_code="g",
                confidence=Decimal("0.9500"),
                review_status="CONFIRMED",
            ),
            ProductImageRow(
                tenant_id=DEFAULT_TENANT_ID,
                product_id=product_id,
                bucket="atc-test",
                object_key=f"products/{product_id}/main.jpg",
                original_filename="main.jpg",
                content_type="image/jpeg",
                byte_size=1024,
                sha256="a" * 64,
                width=800,
                height=800,
                image_role="MAIN",
                approval_status="APPROVED",
            ),
            SupplierProductRow(
                tenant_id=DEFAULT_TENANT_ID,
                supplier_id="SUP-001",
                product_id=product_id,
                supplier_sku="BOWL-A",
                moq=Decimal("100"),
                moq_unit="piece",
                lead_time_days=15,
                status="ACTIVE",
            ),
            SupplierProductRow(
                tenant_id=DEFAULT_TENANT_ID,
                supplier_id="SUP-002",
                product_id=product_id,
                supplier_sku="BOWL-B",
                moq=Decimal("200"),
                moq_unit="piece",
                lead_time_days=20,
                status="ACTIVE",
            ),
            SupplierScoreRow(
                tenant_id=DEFAULT_TENANT_ID,
                supplier_id="SUP-001",
                quality_score=Decimal("92.50"),
                delivery_score=None,
                overall_score=None,
                sample_size=0,
                method_version="manual-v1",
                evidence_summary={"delivery": "unknown"},
            ),
        ])
        session.commit()

        sources = session.scalars(
            select(SupplierProductRow).where(SupplierProductRow.product_id == product_id)
        ).all()
        attribute = session.scalar(
            select(ProductAttributeRow).where(ProductAttributeRow.product_id == product_id)
        )
        score = session.scalar(
            select(SupplierScoreRow).where(SupplierScoreRow.supplier_id == "SUP-001")
            .order_by(SupplierScoreRow.calculated_at.desc())
        )
        assert {source.supplier_id for source in sources} == {"SUP-001", "SUP-002"}
        assert attribute is not None and attribute.value_number == Decimal("200.000000")
        assert score is not None and score.delivery_score is None and score.sample_size == 0

        product = session.get(ProductRow, product_id)
        assert product is not None
        mark_deleted(product)
        session.commit()

    with SessionLocal() as session:
        assert session.get(ProductRow, product_id) is None
        assert session.get(
            ProductRow, product_id, execution_options={"include_deleted": True}
        ) is not None


def test_phase2_typed_attribute_rejects_multiple_value_columns() -> None:
    product_id = uuid4()
    with SessionLocal() as session:
        session.add(ProductRow(
            id=product_id,
            tenant_id=DEFAULT_TENANT_ID,
            product_code=f"INVALID-ATTR-{product_id.hex[:8]}",
            name="Invalid Attribute Test",
        ))
        session.flush()
        session.add(ProductAttributeRow(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=product_id,
            attribute_key="material",
            value_text="rubber",
            value_number=Decimal("1"),
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_phase2_composite_foreign_keys_reject_cross_tenant_links() -> None:
    organization_id = uuid4()
    tenant_id = uuid4()
    supplier_id = f"SUP-{uuid4().hex[:12].upper()}"
    product_id = uuid4()

    with SessionLocal() as session:
        session.add(OrganizationRow(
            id=organization_id,
            code=f"P2-{organization_id.hex[:8]}",
            name="Phase 2 Tenant B",
        ))
        session.flush()
        session.add(TenantRow(
            id=tenant_id,
            organization_id=organization_id,
            slug=f"phase2-{tenant_id.hex[:8]}",
            name="Phase 2 Tenant B",
        ))
        session.flush()
        session.add(SupplierRow(
            id=supplier_id,
            tenant_id=tenant_id,
            supplier_code=supplier_id,
            name="Tenant B Supplier",
        ))
        session.add(ProductRow(
            id=product_id,
            tenant_id=DEFAULT_TENANT_ID,
            product_code=f"CROSS-{product_id.hex[:8]}",
            name="Tenant A Product",
        ))
        session.commit()

        session.add(SupplierProductRow(
            tenant_id=DEFAULT_TENANT_ID,
            supplier_id=supplier_id,
            product_id=product_id,
            supplier_sku="CROSS-TENANT",
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_phase3a_task_route_and_evidence_contract_with_soft_delete() -> None:
    route_id = uuid4()
    task_id = uuid4()
    evidence_id = uuid4()

    with SessionLocal() as session:
        session.add(AIProviderRouteRow(
            id=route_id,
            tenant_id=DEFAULT_TENANT_ID,
            route_key="document-parse-default",
            route_version=1,
            capability="DOCUMENT_PARSE",
            primary_adapter="deterministic-parser",
            fallback_adapters=[],
            routing_policy={"strategy": "primary_then_fallback"},
            retention_policy={"payload": "reference_only"},
            credential_secret_ref=None,
            status="ACTIVE",
            approved_by_membership_id=DEFAULT_MEMBERSHIP_ID,
        ))
        session.flush()
        session.add(AITaskRow(
            id=task_id,
            tenant_id=DEFAULT_TENANT_ID,
            task_type="PRODUCT_DOCUMENT_PARSE",
            task_version=1,
            business_entity_type="IMPORT_JOB",
            business_entity_id="JOB-TRACE-001",
            business_entity_version=1,
            risk_level="L1_ASSISTIVE",
            status="PENDING",
            input_schema_version=1,
            input_ref="s3://controlled-inputs/job-trace-001.json",
            input_hash="1" * 64,
            policy_snapshot={"review_required": True},
            budget_snapshot={"max_attempts": 1},
            requested_by_membership_id=DEFAULT_MEMBERSHIP_ID,
            provider_route_id=route_id,
            route_snapshot={"route_key": "document-parse-default", "route_version": 1},
            idempotency_key="PRODUCT_DOCUMENT_PARSE:JOB-TRACE-001:v1",
        ))
        session.flush()
        session.add(AISourceEvidenceRow(
            id=evidence_id,
            tenant_id=DEFAULT_TENANT_ID,
            ai_task_id=task_id,
            source_entity_type="IMPORT_JOB",
            source_entity_id="JOB-TRACE-001",
            source_version=1,
            location_type="SHEET_CELL_RANGE",
            location={"sheet": "Products", "range": "A2:D2"},
            raw_value_ref="s3://controlled-evidence/job-trace-001/a2-d2",
            raw_value_hash="2" * 64,
            normalized_value_ref="product-draft://JOB-TRACE-001/row/2",
            claim_summary="Product row fields extracted for human review",
            classification="CONFIDENTIAL",
            permission_scope={"roles": ["OWNER", "PURCHASING"]},
            parser_identifier="xlsx-native-parser",
            parser_version="1.0",
            confidence=Decimal("0.9300"),
            evidence_hash="3" * 64,
        ))
        session.commit()

        task = session.get(AITaskRow, task_id)
        evidence = session.get(AISourceEvidenceRow, evidence_id)
        assert task is not None and task.provider_route_id == route_id
        assert task.route_snapshot["route_version"] == 1
        assert evidence is not None and evidence.confidence == Decimal("0.9300")
        mark_deleted(task)
        session.commit()

    with SessionLocal() as session:
        assert session.get(AITaskRow, task_id) is None
        deleted_task = session.get(
            AITaskRow,
            task_id,
            execution_options={"include_deleted": True},
        )
        assert deleted_task is not None and deleted_task.deleted_at is not None
        assert session.get(AISourceEvidenceRow, evidence_id) is not None


def test_phase3a_constraints_enforce_idempotency_and_reference_hashes() -> None:
    route_id = uuid4()
    idempotency_key = f"constraint-test:{uuid4()}"

    with SessionLocal() as session:
        session.add(AIProviderRouteRow(
            id=route_id,
            tenant_id=DEFAULT_TENANT_ID,
            route_key=f"constraint-route-{route_id.hex}",
            route_version=1,
            capability="OCR",
            primary_adapter="fake-ocr",
            fallback_adapters=[],
            routing_policy={},
            retention_policy={},
            status="DRAFT",
        ))
        session.flush()
        session.add(AITaskRow(
            tenant_id=DEFAULT_TENANT_ID,
            task_type="OCR_DOCUMENT",
            input_hash="4" * 64,
            idempotency_key=idempotency_key,
            provider_route_id=route_id,
        ))
        session.commit()

        session.add(AITaskRow(
            tenant_id=DEFAULT_TENANT_ID,
            task_type="OCR_DOCUMENT",
            input_hash="5" * 64,
            idempotency_key=idempotency_key,
            provider_route_id=route_id,
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(AISourceEvidenceRow(
            tenant_id=DEFAULT_TENANT_ID,
            source_entity_type="PRODUCT",
            source_entity_id="INVALID-RAW-REF",
            location_type="ENTITY_FIELD",
            location={"field": "name"},
            raw_value_ref="s3://controlled-evidence/missing-hash",
            raw_value_hash=None,
            evidence_hash="6" * 64,
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_phase3a_composite_foreign_keys_reject_cross_tenant_ai_links() -> None:
    organization_id = uuid4()
    tenant_id = uuid4()
    route_id = uuid4()
    tenant_b_task_id = uuid4()

    with SessionLocal() as session:
        session.add(OrganizationRow(
            id=organization_id,
            code=f"AI-{organization_id.hex[:8]}",
            name="Phase 3A Tenant B",
        ))
        session.flush()
        session.add(TenantRow(
            id=tenant_id,
            organization_id=organization_id,
            slug=f"phase3a-{tenant_id.hex[:8]}",
            name="Phase 3A Tenant B",
        ))
        session.flush()
        session.add(AIProviderRouteRow(
            id=route_id,
            tenant_id=tenant_id,
            route_key="tenant-b-route",
            route_version=1,
            capability="DOCUMENT_PARSE",
            primary_adapter="tenant-b-parser",
            fallback_adapters=[],
            routing_policy={},
            retention_policy={},
            status="ACTIVE",
        ))
        session.commit()

        session.add(AITaskRow(
            tenant_id=DEFAULT_TENANT_ID,
            task_type="CROSS_TENANT_ROUTE",
            input_hash="7" * 64,
            idempotency_key=f"cross-route:{uuid4()}",
            provider_route_id=route_id,
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(AITaskRow(
            id=tenant_b_task_id,
            tenant_id=tenant_id,
            task_type="TENANT_B_TASK",
            input_hash="8" * 64,
            idempotency_key=f"tenant-b:{uuid4()}",
            provider_route_id=route_id,
        ))
        session.commit()

        session.add(AISourceEvidenceRow(
            tenant_id=DEFAULT_TENANT_ID,
            ai_task_id=tenant_b_task_id,
            source_entity_type="PRODUCT",
            source_entity_id="CROSS-TENANT-EVIDENCE",
            location_type="ENTITY_FIELD",
            location={"field": "name"},
            evidence_hash="9" * 64,
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_phase3b_product_projection_is_filtered_idempotent_and_versioned() -> None:
    product_id = uuid4()
    supplier_id = f"KB-{uuid4().hex[:12].upper()}"
    with SessionLocal() as session:
        session.add(SupplierRow(
            id=supplier_id,
            tenant_id=DEFAULT_TENANT_ID,
            supplier_code=supplier_id,
            name="Knowledge Supplier",
            status="ACTIVE",
        ))
        session.add(ProductRow(
            id=product_id,
            tenant_id=DEFAULT_TENANT_ID,
            product_code=f"KB-{product_id.hex[:8]}",
            name="Small Waterproof Rubber Dog Toy",
            description="Durable and non-toxic toy for dogs",
            status="ACTIVE",
            current_version=1,
        ))
        session.flush()
        session.add_all([
            ProductAttributeRow(
                tenant_id=DEFAULT_TENANT_ID,
                product_id=product_id,
                attribute_key="material",
                value_text="TPR",
                review_status="CONFIRMED",
            ),
            ProductAttributeRow(
                tenant_id=DEFAULT_TENANT_ID,
                product_id=product_id,
                attribute_key="market",
                value_text="USA, Brazil",
                review_status="CONFIRMED",
            ),
            ProductAttributeRow(
                tenant_id=DEFAULT_TENANT_ID,
                product_id=product_id,
                attribute_key="internal_ai_note",
                value_text="DO-NOT-PROJECT",
                review_status="AI_SUGGESTED",
            ),
            SupplierProductRow(
                tenant_id=DEFAULT_TENANT_ID,
                supplier_id=supplier_id,
                product_id=product_id,
                supplier_sku="DOG-TPR-10",
                moq=Decimal("100"),
                moq_unit="pcs",
                lead_time_days=15,
                status="ACTIVE",
            ),
            SupplierScoreRow(
                tenant_id=DEFAULT_TENANT_ID,
                supplier_id=supplier_id,
                overall_score=Decimal("88.00"),
                method_version="supplier-score-v1",
            ),
        ])
        session.commit()

        first = project_product_knowledge(
            session, tenant_id=DEFAULT_TENANT_ID, product_id=product_id
        )
        session.commit()
        assert first.idempotent is False
        assert first.chunks == first.embeddings
        assert first.chunks >= 3
        assert first.dimensions == 384

        document = session.get(KnowledgeDocumentRow, first.document_id)
        assert document is not None
        assert document.canonical_payload["attributes"] == [
            {"key": "market", "value": "USA, Brazil"},
            {"key": "material", "value": "TPR"},
        ]
        assert "DO-NOT-PROJECT" not in str(document.canonical_payload)
        chunks = session.scalars(
            select(KnowledgeChunkRow).where(KnowledgeChunkRow.document_id == document.id)
        ).all()
        embeddings = session.scalars(
            select(EmbeddingRow).where(EmbeddingRow.entity_id.in_([chunk.id for chunk in chunks]))
        ).all()
        assert len(embeddings) == len(chunks)
        assert all(len(embedding.embedding) == 384 for embedding in embeddings)
        assert session.get(ProductRow, product_id).search_document_version == 1

        repeated = project_product_knowledge(
            session, tenant_id=DEFAULT_TENANT_ID, product_id=product_id
        )
        session.commit()
        assert repeated.idempotent is True
        assert repeated.document_id == first.document_id

        product = session.get(ProductRow, product_id)
        product.description = "Updated durable waterproof dog toy"
        product.current_version = 2
        session.commit()
        second = project_product_knowledge(
            session, tenant_id=DEFAULT_TENANT_ID, product_id=product_id
        )
        session.commit()
        assert second.document_id != first.document_id
        assert second.source_version == 2
        assert session.get(KnowledgeDocumentRow, first.document_id).status == "STALE"
        assert session.get(KnowledgeDocumentRow, second.document_id).status == "ACTIVE"
        assert all(embedding.status == "STALE" for embedding in embeddings)


def test_phase3b_projection_and_hybrid_search_api_are_testable() -> None:
    waterproof_id = uuid4()
    bowl_id = uuid4()
    with SessionLocal() as session:
        session.add_all([
            ProductRow(
                id=waterproof_id,
                tenant_id=DEFAULT_TENANT_ID,
                product_code=f"WP-{waterproof_id.hex[:8]}",
                name="CometSeries Small Waterproof Rubber Dog Toy",
                description="Durable nontoxic dog toy for outdoor play",
                status="ACTIVE",
            ),
            ProductRow(
                id=bowl_id,
                tenant_id=DEFAULT_TENANT_ID,
                product_code=f"BOWL-{bowl_id.hex[:8]}",
                name="Large Ceramic Pet Bowl",
                description="Heavy ceramic feeding bowl for cats",
                status="ACTIVE",
            ),
        ])
        session.flush()
        session.add_all([
            ProductAttributeRow(
                tenant_id=DEFAULT_TENANT_ID,
                product_id=waterproof_id,
                attribute_key="material",
                value_text="TPR rubber",
                review_status="CONFIRMED",
            ),
            ProductAttributeRow(
                tenant_id=DEFAULT_TENANT_ID,
                product_id=waterproof_id,
                attribute_key="size",
                value_text="10cm small",
                review_status="CONFIRMED",
            ),
            ProductAttributeRow(
                tenant_id=DEFAULT_TENANT_ID,
                product_id=bowl_id,
                attribute_key="material",
                value_text="ceramic",
                review_status="CONFIRMED",
            ),
        ])
        session.commit()

    projection = client.post(f"/api/v1/ai/knowledge/products/{waterproof_id}/project")
    assert projection.status_code == 200
    assert projection.json()["chunks"] == projection.json()["embeddings"]
    repeated = client.post(f"/api/v1/ai/knowledge/products/{waterproof_id}/project")
    assert repeated.status_code == 200 and repeated.json()["idempotent"] is True
    assert client.post(f"/api/v1/ai/knowledge/products/{bowl_id}/project").status_code == 200

    response = client.post(
        "/api/v1/ai/search/products",
        json={"query": "CometSeries small water resistant pet toy", "limit": 10},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ranking_version"] == "hybrid-product-v1"
    assert payload["model"] == {
        "provider": "local",
        "name": "atc-feature-hash",
        "version": "1",
        "dimensions": 384,
    }
    assert payload["results"][0]["product_id"] == str(waterproof_id)
    assert set(payload["results"][0]["score_breakdown"]) == {
        "keyword", "semantic", "attribute", "supplier"
    }
    breakdown = payload["results"][0]["score_breakdown"]
    expected_score = (
        0.35 * breakdown["keyword"]
        + 0.35 * breakdown["semantic"]
        + 0.20 * breakdown["attribute"]
        + 0.10 * breakdown["supplier"]
    )
    assert payload["results"][0]["score"] == pytest.approx(expected_score, abs=0.000002)
    assert payload["results"][0]["evidence"]
    assert payload["results"][0]["supplier_signal_status"] == "UNKNOWN"

    exact = client.post(
        "/api/v1/ai/search/products",
        json={"query": f"WP-{waterproof_id.hex[:8]}", "limit": 10},
    )
    assert exact.status_code == 200
    assert exact.json()["results"][0]["product_id"] == str(waterproof_id)
    assert exact.json()["results"][0]["score_breakdown"]["keyword"] == 1.0


def test_phase3b_tenant_boundaries_apply_to_links_and_retrieval() -> None:
    organization_id = uuid4()
    tenant_b = uuid4()
    product_b = uuid4()
    with SessionLocal() as session:
        session.add(OrganizationRow(
            id=organization_id,
            code=f"KB-{organization_id.hex[:8]}",
            name="Knowledge Tenant B Organization",
        ))
        session.flush()
        session.add(TenantRow(
            id=tenant_b,
            organization_id=organization_id,
            slug=f"knowledge-{tenant_b.hex[:8]}",
            name="Knowledge Tenant B",
        ))
        session.flush()
        session.add(ProductRow(
            id=product_b,
            tenant_id=tenant_b,
            product_code=f"TENANT-B-{product_b.hex[:8]}",
            name="Tenant B Exclusive Solar Lantern",
            description="Exclusive knowledge that Tenant A must never retrieve",
            status="ACTIVE",
        ))
        session.commit()

        session.add(KnowledgeDocumentRow(
            tenant_id=DEFAULT_TENANT_ID,
            source_entity_id=product_b,
            source_version=1,
            title="Illegal cross tenant projection",
            canonical_payload={},
            content_hash="a" * 64,
            permission_scope={},
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        projected = project_product_knowledge(
            session, tenant_id=tenant_b, product_id=product_b
        )
        session.commit()
        assert projected.product_id == product_b
        tenant_a_results = hybrid_product_search(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            query="Tenant B Exclusive Solar Lantern",
        )
        tenant_b_results = hybrid_product_search(
            session,
            tenant_id=tenant_b,
            query="Tenant B Exclusive Solar Lantern",
        )
        assert all(result["product_id"] != product_b for result in tenant_a_results["results"])
        assert tenant_b_results["results"][0]["product_id"] == product_b


def test_phase3b_embedding_validation_rejects_wrong_dimensions_and_nonfinite_values() -> None:
    with pytest.raises(ValueError, match="dimension"):
        validate_vectors([[0.0, 1.0]], expected_count=1, dimensions=3)
    with pytest.raises(ValueError, match="non-finite"):
        validate_vectors([[0.0, float("nan")]], expected_count=1, dimensions=2)


def test_phase4a1a_single_synthetic_xlsx_contract_idempotency_recovery_and_isolation(
    tmp_path: Path,
) -> None:
    xlsx_path = tmp_path / "synthetic-product-intelligence.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Products"
    sheet.append(["Product Name", "Material", "Size", "Color", "MOQ", "Packing"])
    sheet.append(["Waterproof Dog Toy", "TPR", "10cm", "Red", 100, "12 pcs/carton"])
    workbook.save(xlsx_path)
    source_hash = hashlib.sha256(xlsx_path.read_bytes()).hexdigest()

    organization_id = uuid4()
    tenant_b = uuid4()
    source_a_id = f"SRC-{uuid4().hex[:12].upper()}"
    source_b_id = f"SRC-{uuid4().hex[:12].upper()}"
    recovery_source_id = f"SRC-{uuid4().hex[:12].upper()}"
    with SessionLocal() as session:
        session.add(OrganizationRow(
            id=organization_id,
            code=f"PI-{organization_id.hex[:8]}",
            name="Product Intelligence Tenant B Organization",
        ))
        session.flush()
        session.add(TenantRow(
            id=tenant_b,
            organization_id=organization_id,
            slug=f"product-intelligence-{tenant_b.hex[:8]}",
            name="Product Intelligence Tenant B",
        ))
        session.flush()
        for source_id, tenant_id in (
            (source_a_id, DEFAULT_TENANT_ID),
            (source_b_id, tenant_b),
            (recovery_source_id, DEFAULT_TENANT_ID),
        ):
            session.add(SourceFileRow(
                id=source_id,
                tenant_id=tenant_id,
                original_filename=xlsx_path.name,
                stored_filename=f"{source_id}.xlsx",
                local_path=str(xlsx_path),
                sha256=source_hash,
                byte_size=xlsx_path.stat().st_size,
                extension=".xlsx",
                detected_type="OOXML / XLSX",
                extension_matches=True,
                parser="openpyxl",
            ))
        session.commit()

        product_count_before = int(
            session.scalar(select(func.count()).select_from(ProductRow)) or 0
        )
        embedding_count_before = int(
            session.scalar(select(func.count()).select_from(EmbeddingRow)) or 0
        )

        adapter = FakeProductParserAdapter()
        first = run_product_draft_workflow(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            source_file_id=source_a_id,
            parser=adapter,
        )
        session.commit()
        assert first.status == "NEEDS_REVIEW"
        assert first.candidate_fields == 6
        assert first.idempotent is False and first.recovered is False

        candidates = session.scalars(
            select(ProductFieldCandidateRow).where(
                ProductFieldCandidateRow.tenant_id == DEFAULT_TENANT_ID,
                ProductFieldCandidateRow.ai_task_id == first.task_id,
            )
        ).all()
        assert len(candidates) == 6
        assert {candidate.field_key for candidate in candidates} == {
            "name", "material", "specification", "color", "moq", "packing"
        }
        assert all(candidate.review_status == "AI_SUGGESTED" for candidate in candidates)
        material = next(item for item in candidates if item.field_key == "material")
        evidence = session.get(AISourceEvidenceRow, material.source_evidence_id)
        assert evidence is not None
        assert evidence.location == {"sheet": "Products", "range": "B2"}
        assert material.normalized_value == {"value": "TPR"}

        repeated = run_product_draft_workflow(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            source_file_id=source_a_id,
            parser=adapter,
        )
        session.commit()
        assert repeated.idempotent is True
        assert repeated.task_id == first.task_id
        assert repeated.run_id == first.run_id
        assert session.scalar(
            select(func.count())
            .select_from(AIRunRow)
            .where(AIRunRow.ai_task_id == first.task_id)
        ) == 1

        with pytest.raises(ProductWorkflowNotFound):
            run_product_draft_workflow(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                source_file_id=source_b_id,
                parser=adapter,
            )
        tenant_b_result = run_product_draft_workflow(
            session,
            tenant_id=tenant_b,
            source_file_id=source_b_id,
            parser=adapter,
        )
        session.commit()
        assert tenant_b_result.status == "NEEDS_REVIEW"
        tenant_a_candidate_ids = set(
            session.scalars(
                select(ProductFieldCandidateRow.id).where(
                    ProductFieldCandidateRow.tenant_id == DEFAULT_TENANT_ID
                )
            ).all()
        )
        tenant_b_candidate_ids = set(
            session.scalars(
                select(ProductFieldCandidateRow.id).where(
                    ProductFieldCandidateRow.tenant_id == tenant_b
                )
            ).all()
        )
        assert tenant_a_candidate_ids.isdisjoint(tenant_b_candidate_ids)

        recovering_adapter = FakeProductParserAdapter(fail_first_attempt=True)
        failed = run_product_draft_workflow(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            source_file_id=recovery_source_id,
            parser=recovering_adapter,
        )
        session.commit()
        assert failed.status == "PARTIAL"
        assert failed.error_code == "FAKE_TRANSIENT_FAILURE"
        assert failed.candidate_fields == 0
        recovered = run_product_draft_workflow(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            source_file_id=recovery_source_id,
            parser=recovering_adapter,
        )
        session.commit()
        assert recovered.status == "NEEDS_REVIEW"
        assert recovered.recovered is True and recovered.candidate_fields == 6
        recovery_runs = session.scalars(
            select(AIRunRow)
            .where(AIRunRow.ai_task_id == recovered.task_id)
            .order_by(AIRunRow.attempt_number)
        ).all()
        recovery_step = session.scalar(
            select(AITaskStepRow).where(AITaskStepRow.ai_task_id == recovered.task_id)
        )
        assert [run.status for run in recovery_runs] == ["FAILED", "SUCCEEDED"]
        assert recovery_step is not None
        assert recovery_step.status == "SUCCEEDED" and recovery_step.attempt_count == 2

        assert session.scalar(select(func.count()).select_from(ProductRow)) == product_count_before
        assert session.scalar(select(func.count()).select_from(EmbeddingRow)) == embedding_count_before

        tenant_b_candidate = session.scalar(
            select(ProductFieldCandidateRow).where(
                ProductFieldCandidateRow.tenant_id == tenant_b
            )
        )
        assert tenant_b_candidate is not None
        session.add(ProductFieldCandidateRow(
            tenant_id=DEFAULT_TENANT_ID,
            ai_task_id=tenant_b_candidate.ai_task_id,
            ai_run_id=tenant_b_candidate.ai_run_id,
            source_evidence_id=tenant_b_candidate.source_evidence_id,
            candidate_group_key="illegal-cross-tenant",
            candidate_index=0,
            field_key="name",
            raw_value="illegal",
            normalized_value={"value": "illegal"},
            extractor_key="fake-native-product-parser",
            extractor_version="1.0",
            candidate_hash="f" * 64,
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_postgresql_offline_migration_contains_forced_rls_policies() -> None:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql+psycopg://migration-only:unused@localhost/ai_trade_cloud",
    )
    output = io.StringIO()
    config.output_buffer = output
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()

    for table in (
        "organizations",
        "tenants",
        "users",
        "memberships",
        "roles",
        "role_permissions",
        "membership_roles",
        "product_categories",
        "products",
        "product_images",
        "product_attributes",
        "suppliers",
        "supplier_products",
        "supplier_score",
        "source_files",
        "import_jobs",
        "review_items",
        "ai_provider_routes",
        "ai_tasks",
        "ai_source_evidence",
        "knowledge_documents",
        "knowledge_chunks",
        "embeddings",
        "ai_runs",
        "ai_task_steps",
        "product_field_candidates",
        "product_candidate_decisions",
        "product_versions",
        "outbox_events",
    ):
        assert f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY' in sql
        assert f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY' in sql
    assert "app.current_tenant_id" in sql
    assert "app.current_user_id" in sql
    assert "m.deleted_at IS NULL" in sql
    assert "JSONB" in sql
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "VECTOR" in sql
    assert "vector_dims(embedding) = dimensions" in sql
    assert "USING hnsw" in sql
    assert "vector_cosine_ops" in sql
    assert "to_tsvector('simple', content)" in sql


def test_phase3a_migration_upgrades_and_downgrades_as_an_isolated_batch(tmp_path: Path) -> None:
    database_path = tmp_path / "phase3a-migration.db"
    migration_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", migration_url)

    command.upgrade(config, "20260718_0006")
    phase2_engine = create_engine(migration_url)
    with phase2_engine.connect() as connection:
        assert {
            "ai_provider_routes", "ai_tasks", "ai_source_evidence"
        }.isdisjoint(inspect(connection).get_table_names())
    phase2_engine.dispose()

    command.upgrade(config, "20260718_0007")
    phase3a_engine = create_engine(migration_url)
    with phase3a_engine.connect() as connection:
        assert {
            "ai_provider_routes", "ai_tasks", "ai_source_evidence"
        }.issubset(inspect(connection).get_table_names())
        assert {
            "knowledge_documents", "knowledge_chunks", "embeddings"
        }.isdisjoint(inspect(connection).get_table_names())
    phase3a_engine.dispose()

    command.downgrade(config, "20260718_0006")
    downgraded_engine = create_engine(migration_url)
    with downgraded_engine.connect() as connection:
        assert {
            "ai_provider_routes", "ai_tasks", "ai_source_evidence"
        }.isdisjoint(inspect(connection).get_table_names())
        assert "suppliers" in inspect(connection).get_table_names()
    downgraded_engine.dispose()

    command.upgrade(config, "head")
    command.check(config)


def test_phase3b_migration_upgrades_and_downgrades_as_an_isolated_batch(tmp_path: Path) -> None:
    database_path = tmp_path / "phase3b-migration.db"
    migration_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", migration_url)

    command.upgrade(config, "20260718_0007")
    phase3a_engine = create_engine(migration_url)
    with phase3a_engine.connect() as connection:
        assert {
            "knowledge_documents", "knowledge_chunks", "embeddings"
        }.isdisjoint(inspect(connection).get_table_names())
        assert "ai_tasks" in inspect(connection).get_table_names()
    phase3a_engine.dispose()

    command.upgrade(config, "head")
    phase3b_engine = create_engine(migration_url)
    with phase3b_engine.connect() as connection:
        assert {
            "knowledge_documents", "knowledge_chunks", "embeddings"
        }.issubset(inspect(connection).get_table_names())
    phase3b_engine.dispose()

    command.downgrade(config, "20260718_0007")
    downgraded_engine = create_engine(migration_url)
    with downgraded_engine.connect() as connection:
        assert {
            "knowledge_documents", "knowledge_chunks", "embeddings"
        }.isdisjoint(inspect(connection).get_table_names())
        assert "ai_tasks" in inspect(connection).get_table_names()
        assert "products" in inspect(connection).get_table_names()
    downgraded_engine.dispose()

    command.upgrade(config, "head")
    command.check(config)


def test_phase4a1a_migration_upgrades_and_downgrades_as_an_isolated_batch(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "phase4a1a-migration.db"
    migration_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", migration_url)

    command.upgrade(config, "20260718_0008")
    phase3b_engine = create_engine(migration_url)
    with phase3b_engine.connect() as connection:
        assert {"ai_runs", "ai_task_steps", "product_field_candidates"}.isdisjoint(
            inspect(connection).get_table_names()
        )
        assert "embeddings" in inspect(connection).get_table_names()
    phase3b_engine.dispose()

    command.upgrade(config, "head")
    phase4a_engine = create_engine(migration_url)
    with phase4a_engine.connect() as connection:
        assert {"ai_runs", "ai_task_steps", "product_field_candidates"}.issubset(
            inspect(connection).get_table_names()
        )
    phase4a_engine.dispose()

    command.downgrade(config, "20260718_0008")
    downgraded_engine = create_engine(migration_url)
    with downgraded_engine.connect() as connection:
        assert {"ai_runs", "ai_task_steps", "product_field_candidates"}.isdisjoint(
            inspect(connection).get_table_names()
        )
        assert "ai_tasks" in inspect(connection).get_table_names()
        assert "embeddings" in inspect(connection).get_table_names()
    downgraded_engine.dispose()

    command.upgrade(config, "head")
    command.check(config)


def test_phase4a1b_migration_registers_native_provider_and_downgrades(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "phase4a1b-migration.db"
    migration_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", migration_url)

    command.upgrade(config, "20260718_0009")
    phase4a1a_engine = create_engine(migration_url)
    with phase4a1a_engine.connect() as connection:
        checks = inspect(connection).get_check_constraints("ai_runs")
        assert not any("NATIVE" in (item["sqltext"] or "") for item in checks)
    phase4a1a_engine.dispose()

    command.upgrade(config, "head")
    phase4a1b_engine = create_engine(migration_url)
    with phase4a1b_engine.connect() as connection:
        checks = inspect(connection).get_check_constraints("ai_runs")
        assert any("NATIVE" in (item["sqltext"] or "") for item in checks)
    phase4a1b_engine.dispose()

    command.downgrade(config, "20260718_0009")
    downgraded_engine = create_engine(migration_url)
    with downgraded_engine.connect() as connection:
        checks = inspect(connection).get_check_constraints("ai_runs")
        assert not any("NATIVE" in (item["sqltext"] or "") for item in checks)
        assert "product_field_candidates" in inspect(connection).get_table_names()
    downgraded_engine.dispose()

    command.upgrade(config, "head")
    command.check(config)


def test_phase4a1c_migration_adds_adoption_version_and_outbox_contracts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "phase4a1c-migration.db"
    migration_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", migration_url)

    command.upgrade(config, "20260718_0010")
    phase4a1b_engine = create_engine(migration_url)
    with phase4a1b_engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert {
            "product_candidate_decisions",
            "product_versions",
            "outbox_events",
        }.isdisjoint(tables)
        candidate_columns = {
            column["name"]
            for column in inspect(connection).get_columns("product_field_candidates")
        }
        assert "normalization_rule_version" not in candidate_columns
    phase4a1b_engine.dispose()

    command.upgrade(config, "head")
    phase4a1c_engine = create_engine(migration_url)
    with phase4a1c_engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert {
            "product_candidate_decisions",
            "product_versions",
            "outbox_events",
        }.issubset(tables)
        candidate_columns = {
            column["name"]
            for column in inspect(connection).get_columns("product_field_candidates")
        }
        assert {"normalization_rule_version", "normalization_trace"}.issubset(
            candidate_columns
        )
    phase4a1c_engine.dispose()

    command.downgrade(config, "20260718_0010")
    downgraded_engine = create_engine(migration_url)
    with downgraded_engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert {
            "product_candidate_decisions",
            "product_versions",
            "outbox_events",
        }.isdisjoint(tables)
        candidate_columns = {
            column["name"]
            for column in inspect(connection).get_columns("product_field_candidates")
        }
        assert {"normalization_rule_version", "normalization_trace"}.isdisjoint(
            candidate_columns
        )
    downgraded_engine.dispose()

    command.upgrade(config, "head")
    command.check(config)


def test_acg007_migration_adds_quarantine_metadata_and_durable_worker(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "acg007-migration.db"
    migration_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", migration_url)

    command.upgrade(config, "20260718_0012")
    before_engine = create_engine(migration_url)
    with before_engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert {"media_objects", "worker_jobs"}.isdisjoint(tables)
        source_columns = {
            column["name"] for column in inspect(connection).get_columns("source_files")
        }
        assert {"media_object_id", "security_status"}.isdisjoint(source_columns)
    before_engine.dispose()

    command.upgrade(config, "head")
    upgraded_engine = create_engine(migration_url)
    with upgraded_engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert {"media_objects", "worker_jobs"}.issubset(tables)
        source_columns = {
            column["name"] for column in inspect(connection).get_columns("source_files")
        }
        assert {"media_object_id", "security_status"}.issubset(source_columns)
        worker_indexes = {
            index["name"] for index in inspect(connection).get_indexes("worker_jobs")
        }
        assert "ix_worker_jobs_tenant_claim" in worker_indexes
    upgraded_engine.dispose()

    command.downgrade(config, "20260718_0012")
    downgraded_engine = create_engine(migration_url)
    with downgraded_engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert {"media_objects", "worker_jobs"}.isdisjoint(tables)
    downgraded_engine.dispose()

    command.upgrade(config, "head")
    command.check(config)


def test_phase1_5_migration_backfills_nonempty_identity_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "phase1-nonempty.db"
    migration_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", migration_url)
    command.upgrade(config, "20260718_0001")

    populated_engine = create_engine(migration_url)
    permission_id = uuid4().hex
    user_id = uuid4().hex
    with populated_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO permissions (id, code, module, action, description, created_at) "
            "VALUES (?, 'test.permission', 'test', 'permission', NULL, CURRENT_TIMESTAMP)",
            (permission_id,),
        )
        connection.exec_driver_sql(
            "INSERT INTO users "
            "(id, email, display_name, password_hash, identity_provider, identity_subject, locale, "
            "status, is_platform_admin, last_login_at, created_at, updated_at) "
            "VALUES (?, 'same@example.test', 'Existing User', NULL, 'test', 'existing-subject', "
            "'zh-CN', 'active', 0, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (user_id,),
        )
    populated_engine.dispose()

    command.upgrade(config, "head")
    migrated_engine = create_engine(migration_url)
    with migrated_engine.connect() as connection:
        permission = connection.exec_driver_sql(
            "SELECT updated_at, deleted_at FROM permissions WHERE id = ?", (permission_id,)
        ).one()
        user_columns = {column["name"] for column in inspect(connection).get_columns("users")}
        email = connection.exec_driver_sql(
            "SELECT email_normalized FROM users WHERE id = ?", (user_id,)
        ).scalar_one()
        assert permission.updated_at is not None and permission.deleted_at is None
        assert email == "same@example.test"
        assert "password_hash" not in user_columns and "email" not in user_columns
    migrated_engine.dispose()


def test_existing_mvp_schema_is_preserved_across_phase2_upgrade_and_downgrade(tmp_path: Path) -> None:
    database_path = tmp_path / "existing-mvp.db"
    migration_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", migration_url)
    command.upgrade(config, "20260718_0000")

    legacy_engine = create_engine(migration_url)
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO suppliers "
            "(id, name, category, status, active_skus, health, created_at, updated_at) "
            "VALUES ('SUP-KEEP', 'Existing Supplier', 'Legacy', 'active', 12, 'good', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    legacy_engine.dispose()

    command.upgrade(config, "head")

    migrated_engine = create_engine(migration_url)
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(SupplierRow.__table__)) == 1
        assert "organizations" in inspect(connection).get_table_names()
        migrated_supplier = connection.exec_driver_sql(
            "SELECT supplier_code, status, tenant_id FROM suppliers WHERE id = 'SUP-KEEP'"
        ).one()
        assert migrated_supplier.supplier_code == "SUP-KEEP"
        assert migrated_supplier.status == "ACTIVE"
        assert migrated_supplier.tenant_id is not None
    migrated_engine.dispose()

    command.downgrade(config, "20260718_0000")
    downgraded_engine = create_engine(migration_url)
    with downgraded_engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "suppliers" in tables
        assert "organizations" not in tables
        assert connection.scalar(select(func.count()).select_from(SupplierRow.__table__)) == 1
    downgraded_engine.dispose()

    command.upgrade(config, "head")
    command.check(config)


def test_detects_mislabeled_legacy_xls() -> None:
    result = detect_file_type("supplier_quote.xlsx", OLE_SIGNATURE + b"\x00" * 24)
    assert result.detected_type == "OLE / Legacy XLS"
    assert result.parser == "xlrd"
    assert result.extension_matches is False
    assert result.warning is not None


def test_detects_native_csv_and_rejects_csv_extension_masquerade() -> None:
    csv_result = detect_file_type("supplier.csv", b"Product Name,Material,MOQ\r\n")
    assert csv_result.detected_type == "TEXT / CSV"
    assert csv_result.parser == "python-csv"
    assert csv_result.extension_matches is True

    disguised = detect_file_type("supplier.csv", b"PK\x03\x04" + b"\x00" * 28)
    assert disguised.detected_type == "ZIP / OOXML"
    assert disguised.extension_matches is False
    assert disguised.warning is not None


def test_deterministic_margin_calculation() -> None:
    result = calculate_price(PriceCalculationRequest(
        purchase_price=Decimal("72"),
        quantity=500,
        target_margin_rate=Decimal("0.32"),
        currency="CNY",
    ))
    assert result.suggested_unit_price == Decimal("105.88")
    assert result.total_cost == Decimal("36000.00")
    assert result.quotation_total == Decimal("52940.00")
    assert result.gross_profit == Decimal("16940.00")


def test_product_query_and_image_filter() -> None:
    response = client.get("/api/v1/products", params={"q": "围栏", "approved_images_only": True})
    assert response.status_code == 200
    assert [row["model"] for row in response.json()] == ["PF-8G01"]


def test_upload_parse_review_and_approve_xlsx() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "产品表"
    sheet.append(["产品名称", "型号", "单价", "MOQ"])
    sheet.append(["测试宠物碗", "BOWL-001", 12.5, 100])
    content = BytesIO()
    workbook.save(content)

    response = client.post(
        "/api/v1/imports",
        files={"file": ("supplier.xlsx", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"supplier_id": "SUP-001", "source_type": "SUPPLIER_QUOTE"},
    )
    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "needs_review"
    assert job["products"] == 1
    assert job["detected_type"] == "OOXML / XLSX"
    assert job["candidate_status"] == "NEEDS_REVIEW"
    assert job["candidate_fields"] == 4
    assert job["candidate_idempotent"] is False
    assert job["ai_task_id"]

    review_response = client.get("/api/v1/review-items", params={"job_id": job["id"]})
    assert review_response.status_code == 200
    items = review_response.json()
    assert len(items) == 1
    assert items[0]["name"] == "测试宠物碗"
    assert items[0]["status"] == "pending"

    item_id = items[0]["id"]
    update_response = client.patch(
        f"/api/v1/review-items/{item_id}",
        json={"normalized_values": {"name": "测试宠物食盆"}},
    )
    assert update_response.status_code == 200
    name_field = next(field for field in update_response.json()["fields"] if field["key"] == "name")
    assert name_field["normalized"] == "测试宠物食盆"

    approval = client.post(f"/api/v1/review-items/{item_id}/approve")
    assert approval.status_code == 200
    assert approval.json() == {"id": item_id, "status": "approved", "image_status": "SOURCE"}


def test_file_security_clean_upload_promotes_object_before_parsing() -> None:
    response = client.post(
        "/api/v1/imports",
        files={
            "file": (
                "clean-products.csv",
                b"name,model,material\nClean Toy,CLEAN-1,TPR\n",
                "text/csv",
            )
        },
        data={"supplier_id": "SUP-001", "source_type": "SUPPLIER_QUOTE"},
    )
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]
    with SessionLocal() as session:
        import_job = session.get(ImportJobRow, job_id)
        assert import_job is not None
        source = import_job.source_file
        assert source.security_status == "ACCEPTED"
        assert source.media_object_id is not None
        media = session.get(MediaObjectRow, source.media_object_id)
        assert media is not None
        assert (media.zone, media.status, media.scan_status) == (
            "SOURCE",
            "AVAILABLE",
            "CLEAN",
        )
        worker_job = session.scalar(
            select(WorkerJobRow).where(WorkerJobRow.import_job_id == job_id)
        )
        assert worker_job is not None
        assert worker_job.status == "SUCCEEDED"
        assert worker_job.checkpoint["outcome"] == "PARSED"
        source_key = media.object_key
    storage = get_object_storage()
    source_path = storage.local_path(source_key)
    assert source_path is not None and source_path.is_file()
    quarantine_path = storage.local_path(
        source_key.replace("/source/", "/quarantine/", 1)
    )
    assert quarantine_path is not None and not quarantine_path.exists()


def test_malware_marker_stays_quarantined_and_never_reaches_parser() -> None:
    response = client.post(
        "/api/v1/imports",
        files={
            "file": (
                "malicious.csv",
                b"name,model\nATC-MALWARE-TEST,BLOCKED-1\n",
                "text/csv",
            )
        },
        data={"supplier_id": "SUP-001", "source_type": "SUPPLIER_QUOTE"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["candidate_fields"] == 0
    with SessionLocal() as session:
        import_job = session.get(ImportJobRow, payload["id"])
        assert import_job is not None
        source = import_job.source_file
        media = session.get(MediaObjectRow, source.media_object_id)
        worker_job = session.scalar(
            select(WorkerJobRow).where(WorkerJobRow.import_job_id == import_job.id)
        )
        assert media is not None and worker_job is not None
        assert source.security_status == "QUARANTINED"
        assert (media.zone, media.status, media.scan_status) == (
            "QUARANTINE",
            "REJECTED",
            "INFECTED",
        )
        assert worker_job.status == "SUCCEEDED"
        assert worker_job.checkpoint["outcome"] == "QUARANTINED"
        assert session.scalar(
            select(func.count()).select_from(ReviewItemRow).where(
                ReviewItemRow.job_id == import_job.id
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(AITaskRow).where(
                AITaskRow.business_entity_id == source.id
            )
        ) == 0


def test_persistent_file_worker_recovers_scanner_failure_and_expired_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FILE_WORKER_INLINE", "false")
    response = client.post(
        "/api/v1/imports",
        files={
            "file": (
                "recoverable.csv",
                b"name,model\nRecovered Toy,RECOVER-1\n",
                "text/csv",
            )
        },
        data={"supplier_id": "SUP-001", "source_type": "SUPPLIER_QUOTE"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "scanning"
    import_job_id = response.json()["id"]
    with SessionLocal() as session:
        worker_job = session.scalar(
            select(WorkerJobRow).where(WorkerJobRow.import_job_id == import_job_id)
        )
        assert worker_job is not None and worker_job.status == "PENDING"
        worker_job_id = worker_job.id

    class UnavailableScanner:
        engine_name = "unavailable-test-scanner"

        def scan(self, _path: Path) -> object:
            raise ConnectionError("scanner unavailable")

    first_now = datetime.now(UTC)
    with SessionLocal() as session:
        failed = process_file_worker_job(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            job_id=worker_job_id,
            worker_id="worker-before-restart",
            scanner=UnavailableScanner(),  # type: ignore[arg-type]
            now=first_now,
        )
    assert failed.status == "RETRY"

    with SessionLocal() as session:
        worker_job = session.get(WorkerJobRow, worker_job_id)
        assert worker_job is not None
        worker_job.status = "RUNNING"
        worker_job.lease_owner = "crashed-worker"
        worker_job.lease_expires_at = first_now - timedelta(seconds=1)
        session.commit()

    with SessionLocal() as session:
        recovered = process_file_worker_job(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            job_id=worker_job_id,
            worker_id="worker-after-restart",
            scanner=DeterministicDevelopmentScanner(),
            now=first_now + timedelta(seconds=5),
        )
    assert recovered.status == "SUCCEEDED"
    assert recovered.outcome == "PARSED"
    with SessionLocal() as session:
        worker_job = session.get(WorkerJobRow, worker_job_id)
        import_job = session.get(ImportJobRow, import_job_id)
        assert worker_job is not None and import_job is not None
        assert worker_job.attempt_count == 2
        assert worker_job.lease_owner is None
        assert import_job.status == "needs_review"


def test_development_scanner_is_fail_closed_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FILE_SCANNER_PROFILE", "development")
    with pytest.raises(RuntimeError, match="forbidden in production"):
        get_file_scanner()


def test_phase4a1b_real_csv_upload_candidate_evidence_and_content_idempotency() -> None:
    content = (
        "Product Name,SKU,Material,Size,MOQ,Packing\r\n"
        "Waterproof Dog Toy,DOG-001,TPR,10cm,100,12 pcs/carton\r\n"
    ).encode("utf-8-sig")

    with SessionLocal() as session:
        product_count_before = int(
            session.scalar(select(func.count()).select_from(ProductRow)) or 0
        )
        embedding_count_before = int(
            session.scalar(select(func.count()).select_from(EmbeddingRow)) or 0
        )

    first_response = client.post(
        "/api/v1/imports",
        files={"file": ("supplier_products.csv", content, "text/csv")},
        data={"supplier_id": "SUP-001", "source_type": "SUPPLIER_CATALOG"},
    )
    assert first_response.status_code == 201
    first = first_response.json()
    assert first["detected_type"] == "TEXT / CSV"
    assert first["parser"] == "python-csv"
    assert first["products"] == 1
    assert first["candidate_status"] == "NEEDS_REVIEW"
    assert first["candidate_fields"] == 6
    assert first["candidate_idempotent"] is False

    candidates_response = client.get(
        f"/api/v1/ai/product-intelligence/tasks/{first['ai_task_id']}/candidates"
    )
    assert candidates_response.status_code == 200
    candidates = candidates_response.json()
    assert len(candidates) == 6
    assert all(item["review_status"] == "AI_SUGGESTED" for item in candidates)
    material = next(item for item in candidates if item["field_key"] == "material")
    assert material["raw_value"] == "TPR"
    assert material["evidence"]["location"] == {
        "sheet": "supplier_products",
        "range": "C2",
    }
    assert len(material["evidence"]["raw_value_hash"]) == 64

    repeated_response = client.post(
        "/api/v1/imports",
        files={"file": ("renamed_supplier_file.csv", content, "text/csv")},
        data={"supplier_id": "SUP-001", "source_type": "SUPPLIER_CATALOG"},
    )
    assert repeated_response.status_code == 201
    repeated = repeated_response.json()
    assert repeated["ai_task_id"] == first["ai_task_id"]
    assert repeated["candidate_fields"] == 6
    assert repeated["candidate_idempotent"] is True

    with SessionLocal() as session:
        task_id = UUID(first["ai_task_id"])
        runs = session.scalars(
            select(AIRunRow).where(AIRunRow.ai_task_id == task_id)
        ).all()
        assert len(runs) == 1
        assert runs[0].provider_type == "NATIVE"
        assert runs[0].usage == {}
        assert session.scalar(select(func.count()).select_from(ProductRow)) == product_count_before
        assert session.scalar(select(func.count()).select_from(EmbeddingRow)) == embedding_count_before


def test_phase4a1b_native_pipeline_recovers_when_source_file_becomes_available(
    tmp_path: Path,
) -> None:
    content = (
        "Product Name,Material,MOQ\r\n"
        "Recoverable Dog Toy,TPR,200\r\n"
    ).encode("utf-8")
    missing_path = tmp_path / "temporarily-unavailable.csv"
    source_id = f"SRC-{uuid4().hex[:12].upper()}"
    source_hash = hashlib.sha256(content).hexdigest()

    with SessionLocal() as session:
        session.add(SourceFileRow(
            id=source_id,
            tenant_id=DEFAULT_TENANT_ID,
            original_filename="recoverable.csv",
            stored_filename=missing_path.name,
            local_path=str(missing_path),
            sha256=source_hash,
            byte_size=len(content),
            extension=".csv",
            detected_type="TEXT / CSV",
            extension_matches=True,
            parser="python-csv",
        ))
        session.commit()

        first = run_product_draft_workflow(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            source_file_id=source_id,
            parser=NativeSupplierFileParserAdapter(),
        )
        session.commit()
        assert first.status == "PARTIAL"
        assert first.error_code == "PRODUCT_DRAFT_PIPELINE_FAILURE"
        assert first.candidate_fields == 0

        missing_path.write_bytes(content)
        second = run_product_draft_workflow(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            source_file_id=source_id,
            parser=NativeSupplierFileParserAdapter(),
        )
        session.commit()
        assert second.status == "NEEDS_REVIEW"
        assert second.recovered is True
        assert second.candidate_fields == 3
        runs = session.scalars(
            select(AIRunRow)
            .where(AIRunRow.ai_task_id == second.task_id)
            .order_by(AIRunRow.attempt_number)
        ).all()
        assert [(run.attempt_number, run.status) for run in runs] == [
            (1, "FAILED"),
            (2, "SUCCEEDED"),
        ]


def test_phase4a1c_deterministic_normalization_preserves_rules_and_review_warnings() -> None:
    capacity = normalize_product_field("capacity", "3000 ml")
    assert capacity.value == {"value": "3", "unit": "L"}
    assert capacity.unit == "L"
    assert capacity.rule_version == "product-normalization-v1"
    assert any(step["rule"] == "millilitre-to-litre" for step in capacity.trace)

    dimensions = normalize_product_field("specification", "10 x 8 x 5 CM")
    assert dimensions.value == {
        "dimensions": ["10", "8", "5"],
        "axis_order": "UNCONFIRMED",
        "unit": "cm",
    }
    assert dimensions.validation_status == "WARNING"
    assert "DIMENSION_AXIS_ORDER_REVIEW_REQUIRED" in dimensions.warnings

    unknown_material = normalize_product_field("material", "Supplier Secret Blend")
    assert unknown_material.value == {"value": "Supplier Secret Blend"}
    assert "MATERIAL_VOCABULARY_REVIEW_REQUIRED" in unknown_material.warnings

    colors = normalize_product_field("color", "Red / Blue")
    assert colors.value["variant_relation"] == "UNCONFIRMED"
    assert "COLOR_VARIANT_RELATION_REVIEW_REQUIRED" in colors.warnings

    invalid_moq = normalize_product_field("moq", "-10 pcs")
    assert invalid_moq.validation_status == "FAILED"
    assert "MOQ_MUST_BE_NONNEGATIVE" in invalid_moq.warnings


def test_phase4a1c_human_adoption_versions_outbox_projection_and_failure_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workbook_path = tmp_path / "phase4a1c-products.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Products"
    sheet.append(["Product Name", "Item No", "Material", "Size", "Color", "MOQ", "Packing"])
    sheet.append(["Waterproof Dog Toy", "DOG-100", "TPR", "10 x 8 x 5 cm", "Red / Blue", 100, "12 pcs/carton"])
    sheet.append(["Durable Dog Ball", "DOG-200", "Rubber", "8 cm", "Green", 200, "24 pcs/carton"])
    workbook.save(workbook_path)
    source_hash = hashlib.sha256(workbook_path.read_bytes()).hexdigest()
    source_id = f"SRC-{uuid4().hex[:12].upper()}"
    job_id = f"JOB-{uuid4().hex[:12].upper()}"

    with SessionLocal() as session:
        supplier = session.scalar(
            select(SupplierRow).where(
                SupplierRow.tenant_id == DEFAULT_TENANT_ID,
                SupplierRow.status == "ACTIVE",
            )
        )
        assert supplier is not None
        session.add(SourceFileRow(
            id=source_id,
            tenant_id=DEFAULT_TENANT_ID,
            original_filename=workbook_path.name,
            stored_filename=workbook_path.name,
            local_path=str(workbook_path),
            sha256=source_hash,
            byte_size=workbook_path.stat().st_size,
            extension=".xlsx",
            detected_type="OOXML / XLSX",
            extension_matches=True,
            parser="openpyxl",
        ))
        session.add(ImportJobRow(
            id=job_id,
            tenant_id=DEFAULT_TENANT_ID,
            source_file_id=source_id,
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            source_type="SUPPLIER_CATALOG",
            status="needs_review",
            progress=100,
            products_count=2,
        ))
        session.commit()
        workflow = run_product_draft_workflow(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            source_file_id=source_id,
            parser=NativeSupplierFileParserAdapter(),
            idempotency_context=f"supplier:{supplier.id}",
        )
        session.commit()
        candidates = session.scalars(
            select(ProductFieldCandidateRow)
            .where(
                ProductFieldCandidateRow.tenant_id == DEFAULT_TENANT_ID,
                ProductFieldCandidateRow.ai_task_id == workflow.task_id,
            )
            .order_by(ProductFieldCandidateRow.candidate_index, ProductFieldCandidateRow.field_key)
        ).all()
        groups: dict[str, dict[str, str]] = {}
        for candidate in candidates:
            groups.setdefault(candidate.candidate_group_key, {})[candidate.field_key] = candidate.raw_value
        ordered_groups = list(groups.items())
        assert len(ordered_groups) == 2
        assert all(candidate.normalization_rule_version == "product-normalization-v1" for candidate in candidates)
        assert all(candidate.normalization_trace for candidate in candidates)
        product_count_before = int(
            session.scalar(select(func.count()).select_from(ProductRow)) or 0
        )
        knowledge_count_before = int(
            session.scalar(select(func.count()).select_from(KnowledgeDocumentRow)) or 0
        )

    first_group_key, first_values = ordered_groups[0]
    approval_payload = {
        "idempotency_key": f"approve-{uuid4()}",
        "confirmed_values": first_values,
        "activate": True,
        "product_code": f"ATC-{uuid4().hex[:10].upper()}",
        "change_reason": "Phase 4A-1C human acceptance test",
    }
    approve_response = client.post(
        f"/api/v1/ai/product-intelligence/tasks/{workflow.task_id}/groups/{first_group_key}/approve",
        json=approval_payload,
    )
    assert approve_response.status_code == 202
    approved = approve_response.json()
    assert approved["product_version"] == 1
    assert approved["outbox_status"] == "PENDING"
    assert approved["idempotent"] is False

    repeated_response = client.post(
        f"/api/v1/ai/product-intelligence/tasks/{workflow.task_id}/groups/{first_group_key}/approve",
        json=approval_payload,
    )
    assert repeated_response.status_code == 202
    repeated = repeated_response.json()
    assert repeated["decision_id"] == approved["decision_id"]
    assert repeated["product_id"] == approved["product_id"]
    assert repeated["idempotent"] is True

    reviewed_candidates = client.get(
        f"/api/v1/ai/product-intelligence/tasks/{workflow.task_id}/candidates"
    )
    assert reviewed_candidates.status_code == 200
    reviewed_first_group = [
        item
        for item in reviewed_candidates.json()
        if item["candidate_group_key"] == first_group_key
    ]
    assert reviewed_first_group
    assert all(item["review_status"] == "AI_SUGGESTED" for item in reviewed_first_group)
    assert all(item["latest_decision"]["action"] == "APPROVE" for item in reviewed_first_group)
    assert all(item["latest_decision"]["status"] == "APPLIED" for item in reviewed_first_group)
    assert all(item["latest_decision"]["product_id"] == approved["product_id"] for item in reviewed_first_group)

    with SessionLocal() as session:
        product_id = UUID(approved["product_id"])
        outbox_event_id = UUID(approved["outbox_event_id"])
        product = session.scalar(
            select(ProductRow).where(
                ProductRow.tenant_id == DEFAULT_TENANT_ID,
                ProductRow.id == product_id,
            )
        )
        assert product is not None
        assert product.name == "Waterproof Dog Toy"
        assert product.status == "ACTIVE"
        assert product.current_version == 1
        assert product.search_document_version == 0
        assert session.scalar(
            select(func.count())
            .select_from(ProductVersionRow)
            .where(ProductVersionRow.product_id == product_id)
        ) == 1
        decision = session.get(ProductCandidateDecisionRow, UUID(approved["decision_id"]))
        assert decision is not None
        assert decision.normalization_snapshot["material"]["raw_value"] == "TPR"
        assert decision.normalization_snapshot["material"]["human_value"] == "TPR"
        assert decision.reviewed_by_membership_id == DEFAULT_MEMBERSHIP_ID
        task = session.get(AITaskRow, workflow.task_id)
        assert task is not None and task.status == "NEEDS_REVIEW"
        attributes = session.scalars(
            select(ProductAttributeRow).where(
                ProductAttributeRow.tenant_id == DEFAULT_TENANT_ID,
                ProductAttributeRow.product_id == product_id,
            )
        ).all()
        assert attributes
        assert all(attribute.review_status == "CONFIRMED" for attribute in attributes)
        assert any(attribute.attribute_key == "material" and attribute.value_text == "TPR" for attribute in attributes)
        supplier_product = session.scalar(
            select(SupplierProductRow).where(
                SupplierProductRow.tenant_id == DEFAULT_TENANT_ID,
                SupplierProductRow.product_id == product_id,
            )
        )
        assert supplier_product is not None
        assert supplier_product.supplier_sku == "DOG-100"
        assert supplier_product.moq == Decimal("100")
        assert supplier_product.moq_unit == "piece"
        assert session.scalar(
            select(func.count())
            .select_from(KnowledgeDocumentRow)
            .where(KnowledgeDocumentRow.source_entity_id == product_id)
        ) == 0

        dispatched = dispatch_product_committed_event(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            event_id=outbox_event_id,
        )
        session.commit()
        assert dispatched.status == "PUBLISHED"
        assert dispatched.document_id is not None
        session.refresh(product)
        assert product.search_document_version == 1
        assert session.scalar(
            select(func.count())
            .select_from(KnowledgeDocumentRow)
            .where(
                KnowledgeDocumentRow.source_entity_id == product_id,
                KnowledgeDocumentRow.source_version == 1,
                KnowledgeDocumentRow.status == "ACTIVE",
            )
        ) == 1
        repeated_dispatch = dispatch_product_committed_event(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            event_id=outbox_event_id,
        )
        assert repeated_dispatch.idempotent is True

        with pytest.raises(ProductAdoptionError) as duplicate_group:
            approve_candidate_group(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                task_id=workflow.task_id,
                candidate_group_key=first_group_key,
                reviewer_membership_id=DEFAULT_MEMBERSHIP_ID,
                idempotency_key=f"approve-{uuid4()}",
                confirmed_values=first_values,
                activate=True,
            )
        assert duplicate_group.value.code == "CANDIDATE_GROUP_ALREADY_APPLIED"

    second_group_key, second_values = ordered_groups[1]
    reject_response = client.post(
        f"/api/v1/ai/product-intelligence/tasks/{workflow.task_id}/groups/{second_group_key}/reject",
        json={
            "idempotency_key": f"reject-{uuid4()}",
            "reason": "Human reviewer requests a corrected source row",
        },
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "RECORDED"
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(ProductRow)) == product_count_before + 1
        task = session.get(AITaskRow, workflow.task_id)
        assert task is not None and task.status == "SUCCEEDED"

    second_approval = client.post(
        f"/api/v1/ai/product-intelligence/tasks/{workflow.task_id}/groups/{second_group_key}/approve",
        json={
            "idempotency_key": f"approve-{uuid4()}",
            "confirmed_values": second_values,
            "activate": True,
            "product_code": f"ATC-{uuid4().hex[:10].upper()}",
        },
    )
    assert second_approval.status_code == 202
    second = second_approval.json()

    import app.services.product_intelligence.adoption as adoption_module

    def fail_projection(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic projector outage")

    monkeypatch.setattr(adoption_module, "project_product_knowledge", fail_projection)
    with SessionLocal() as session:
        failed_dispatch = dispatch_product_committed_event(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            event_id=UUID(second["outbox_event_id"]),
        )
        session.commit()
        assert failed_dispatch.status == "FAILED"
        assert failed_dispatch.error_code == "KNOWLEDGE_PROJECTION_FAILED"
        persisted_product = session.scalar(
            select(ProductRow).where(ProductRow.id == UUID(second["product_id"]))
        )
        assert persisted_product is not None
        assert persisted_product.status == "ACTIVE"
        assert persisted_product.search_document_version == 0
        failed_event = session.get(OutboxEventRow, UUID(second["outbox_event_id"]))
        assert failed_event is not None and failed_event.attempt_count == 1
        assert session.scalar(select(func.count()).select_from(ProductRow)) == product_count_before + 2
        assert session.scalar(select(func.count()).select_from(KnowledgeDocumentRow)) == knowledge_count_before + 1

        organization_id = uuid4()
        tenant_b = uuid4()
        membership_b = uuid4()
        session.add(OrganizationRow(
            id=organization_id,
            code=f"P1C-{organization_id.hex[:8]}",
            name="Phase 4A-1C Isolation Organization",
        ))
        session.flush()
        session.add(TenantRow(
            id=tenant_b,
            organization_id=organization_id,
            slug=f"phase4a1c-{tenant_b.hex[:8]}",
            name="Phase 4A-1C Tenant B",
        ))
        session.flush()
        session.add(MembershipRow(
            id=membership_b,
            tenant_id=tenant_b,
            user_id=DEFAULT_OWNER_USER_ID,
            status="active",
        ))
        session.commit()
        with pytest.raises(ProductAdoptionError) as cross_tenant:
            approve_candidate_group(
                session,
                tenant_id=tenant_b,
                task_id=workflow.task_id,
                candidate_group_key=first_group_key,
                reviewer_membership_id=membership_b,
                idempotency_key=f"approve-{uuid4()}",
                confirmed_values=first_values,
                activate=True,
            )
        assert cross_tenant.value.code == "CANDIDATE_GROUP_NOT_FOUND"


def test_phase4a1c_update_requires_expected_version_and_creates_new_snapshot(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "phase4a1c-update.csv"
    source_path.write_text(
        "Product Name,Material,MOQ\nVersioned Product Updated,Silicone,300\n",
        encoding="utf-8",
    )
    source_id = f"SRC-{uuid4().hex[:12].upper()}"
    job_id = f"JOB-{uuid4().hex[:12].upper()}"
    product_id = uuid4()
    with SessionLocal() as session:
        supplier = session.scalar(
            select(SupplierRow).where(SupplierRow.tenant_id == DEFAULT_TENANT_ID)
        )
        assert supplier is not None
        session.add(ProductRow(
            id=product_id,
            tenant_id=DEFAULT_TENANT_ID,
            product_code=f"LEGACY-{uuid4().hex[:8]}",
            name="Versioned Product Original",
            status="ACTIVE",
            current_version=1,
            search_document_version=0,
            created_by=DEFAULT_OWNER_USER_ID,
            updated_by=DEFAULT_OWNER_USER_ID,
        ))
        session.add(SourceFileRow(
            id=source_id,
            tenant_id=DEFAULT_TENANT_ID,
            original_filename=source_path.name,
            stored_filename=source_path.name,
            local_path=str(source_path),
            sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
            byte_size=source_path.stat().st_size,
            extension=".csv",
            detected_type="TEXT / CSV",
            extension_matches=True,
            parser="python-csv",
        ))
        session.add(ImportJobRow(
            id=job_id,
            tenant_id=DEFAULT_TENANT_ID,
            source_file_id=source_id,
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            status="needs_review",
            progress=100,
        ))
        session.commit()
        workflow = run_product_draft_workflow(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            source_file_id=source_id,
            parser=NativeSupplierFileParserAdapter(),
            idempotency_context=f"supplier:{supplier.id}",
        )
        session.commit()
        candidates = session.scalars(
            select(ProductFieldCandidateRow).where(
                ProductFieldCandidateRow.ai_task_id == workflow.task_id
            )
        ).all()
        group_key = candidates[0].candidate_group_key
        values = {candidate.field_key: candidate.raw_value for candidate in candidates}

        with pytest.raises(ProductAdoptionError) as missing_version:
            approve_candidate_group(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                task_id=workflow.task_id,
                candidate_group_key=group_key,
                reviewer_membership_id=DEFAULT_MEMBERSHIP_ID,
                idempotency_key=f"approve-{uuid4()}",
                confirmed_values=values,
                activate=True,
                target_product_id=product_id,
            )
        assert missing_version.value.code == "EXPECTED_PRODUCT_VERSION_REQUIRED"
        session.rollback()

        result = approve_candidate_group(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            task_id=workflow.task_id,
            candidate_group_key=group_key,
            reviewer_membership_id=DEFAULT_MEMBERSHIP_ID,
            idempotency_key=f"approve-{uuid4()}",
            confirmed_values=values,
            activate=True,
            target_product_id=product_id,
            expected_product_version=1,
        )
        session.commit()
        assert result.product_version == 2
        product = session.get(ProductRow, product_id)
        assert product is not None and product.current_version == 2
        assert product.name == "Versioned Product Updated"
        versions = session.scalars(
            select(ProductVersionRow)
            .where(ProductVersionRow.product_id == product_id)
            .order_by(ProductVersionRow.version_number)
        ).all()
        assert [version.version_number for version in versions] == [1, 2]
        assert versions[0].snapshot["product"]["name"] == "Versioned Product Original"
        assert versions[1].snapshot["product"]["name"] == "Versioned Product Updated"
        assert versions[0].content_hash != versions[1].content_hash

        versions[1].change_reason = "attempted history rewrite"
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        with pytest.raises(ProductAdoptionError) as conflict:
            approve_candidate_group(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                task_id=workflow.task_id,
                candidate_group_key=group_key,
                reviewer_membership_id=DEFAULT_MEMBERSHIP_ID,
                idempotency_key=f"approve-{uuid4()}",
                confirmed_values=values,
                activate=True,
                target_product_id=product_id,
                expected_product_version=1,
            )
        assert conflict.value.code == "CANDIDATE_GROUP_ALREADY_APPLIED"


def test_multiline_catalog_header_does_not_pollute_field_mapping(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["某供应商产品规格与联系方式"])
    sheet.append(["大类", "产品名称", "产品尺寸", "叠装箱规"])
    sheet.append(["饮水机", "宠物饮水机", "20*20*16", "60*60*60/24套"])
    path = tmp_path / "catalog.xlsx"
    workbook.save(path)

    result = parse_document(path, detect_file_path(path, path.name))
    assert len(result.records) == 1
    fields = {field["key"]: field["source"] for field in result.records[0].fields}
    assert fields == {
        "name": "宠物饮水机",
        "category": "饮水机",
        "specification": "20*20*16",
        "packing": "60*60*60/24套",
    }


def test_outbox_relay_retry_dead_letter_expired_lease_and_metrics(
    tmp_path: Path,
) -> None:
    event_id = _create_pending_product_event(tmp_path, suffix=uuid4().hex[:6])
    start = datetime.now(UTC)
    failing = InMemoryOutboxPublisher(fail_with=RuntimeError("broker unavailable"))
    with SessionLocal() as session:
        event = session.get(OutboxEventRow, event_id)
        assert event is not None
        event.max_attempts = 2
        session.commit()
        first = relay_one_outbox_event(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            relay_id="relay-a",
            publisher=failing,
            event_id=event_id,
            now=start,
        )
        assert first.status == "FAILED"
        assert first.outcome == "RETRY_SCHEDULED"
        assert first.attempt_count == 1
        assert first.next_attempt_at is not None
        not_due = relay_one_outbox_event(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            relay_id="relay-a",
            publisher=failing,
            event_id=event_id,
            now=start,
        )
        assert not_due.status == "IDLE"
        second = relay_one_outbox_event(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            relay_id="relay-b",
            publisher=failing,
            event_id=event_id,
            now=first.next_attempt_at + timedelta(seconds=1),
        )
        assert second.status == "DEAD"
        assert second.outcome == "DEAD_LETTERED"
        assert second.attempt_count == 2

    lease_event_id = _create_pending_product_event(tmp_path, suffix=uuid4().hex[:6])
    publisher = InMemoryOutboxPublisher()
    with SessionLocal() as session:
        lease_event = session.get(OutboxEventRow, lease_event_id)
        assert lease_event is not None
        lease_event.status = "PROCESSING"
        lease_event.lease_owner = "crashed-relay"
        lease_event.lease_expires_at = start - timedelta(seconds=1)
        session.commit()
        recovered = relay_one_outbox_event(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            relay_id="replacement-relay",
            publisher=publisher,
            event_id=lease_event_id,
            now=start,
        )
        assert recovered.status == "PUBLISHED"
        assert recovered.attempt_count == 1
        assert [message.event_id for message in publisher.messages] == [lease_event_id]

    metrics = client.get("/api/v1/system/outbox/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["dead_count"] >= 1
    assert metrics.json()["lag_seconds"] >= 0


def test_outbox_relay_at_least_once_inbox_idempotency_and_tenant_boundary(
    tmp_path: Path,
) -> None:
    event_id = _create_pending_product_event(tmp_path, suffix=uuid4().hex[:6])
    publisher = InMemoryOutboxPublisher()
    with SessionLocal() as session:
        wrong_tenant = relay_one_outbox_event(
            session,
            tenant_id=uuid4(),
            relay_id="relay-wrong-tenant",
            publisher=publisher,
            event_id=event_id,
        )
        assert wrong_tenant.status == "IDLE"
        delivered = relay_one_outbox_event(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            relay_id="relay-primary",
            publisher=publisher,
            event_id=event_id,
        )
        assert delivered.status == "PUBLISHED"
        duplicate_relay = relay_one_outbox_event(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            relay_id="relay-primary",
            publisher=publisher,
            event_id=event_id,
        )
        assert duplicate_relay.outcome == "ALREADY_PUBLISHED"
        assert len(publisher.messages) == 1

    message = publisher.messages[0]
    with SessionLocal() as session:
        first = consume_product_committed_message(session, message=message)
        session.commit()
        assert first.status == "COMPLETED"
        assert first.idempotent is False
        repeated = consume_product_committed_message(session, message=message)
        session.commit()
        assert repeated.status == "COMPLETED"
        assert repeated.idempotent is True
        assert repeated.inbox_id == first.inbox_id
        forged = replace(message, payload={**message.payload, "product_version": 999})
        with pytest.raises(ProductAdoptionError) as integrity_error:
            consume_product_committed_message(session, message=forged)
        assert integrity_error.value.code == "OUTBOX_MESSAGE_INTEGRITY_FAILED"
        assert session.scalar(
            select(func.count()).select_from(InboxEventRow).where(
                InboxEventRow.tenant_id == DEFAULT_TENANT_ID,
                InboxEventRow.event_id == event_id,
            )
        ) == 1


def test_memory_outbox_publisher_is_fail_closed_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("OUTBOX_PUBLISHER_PROFILE", "memory")
    with pytest.raises(RuntimeError, match="forbidden"):
        get_outbox_publisher()


def test_acg008_through_acg010_migrations_are_reversible(tmp_path: Path) -> None:
    database_path = tmp_path / "acg008-009-migration.db"
    migration_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", migration_url)

    command.upgrade(config, "20260718_0013")
    before_relay = create_engine(migration_url)
    with before_relay.connect() as connection:
        assert "inbox_events" not in inspect(connection).get_table_names()
        outbox_columns = {
            column["name"] for column in inspect(connection).get_columns("outbox_events")
        }
        assert {"available_at", "lease_owner", "dead_lettered_at"}.isdisjoint(
            outbox_columns
        )
    before_relay.dispose()

    command.upgrade(config, "20260718_0014")
    relay_engine = create_engine(migration_url)
    with relay_engine.connect() as connection:
        assert "inbox_events" in inspect(connection).get_table_names()
        outbox_columns = {
            column["name"] for column in inspect(connection).get_columns("outbox_events")
        }
        assert {"available_at", "lease_owner", "dead_lettered_at"}.issubset(
            outbox_columns
        )
        assert {
            "skus",
            "attribute_definitions",
            "supplier_prices",
            "product_audit_events",
        }.isdisjoint(inspect(connection).get_table_names())
    relay_engine.dispose()

    command.upgrade(config, "head")
    product_engine = create_engine(migration_url)
    with product_engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert {
            "skus",
            "attribute_definitions",
            "supplier_prices",
            "product_audit_events",
            "vision_observations",
            "image_embeddings",
            "image_searches",
            "customers",
            "inquiries",
            "inquiry_items",
            "inquiry_match_results",
            "quotations",
            "quotation_versions",
            "quotation_items",
            "quotation_approvals",
            "tenant_public_profiles",
            "public_catalog_offers",
            "public_quote_drafts",
            "public_quote_draft_items",
            "public_quote_download_tokens",
        }.issubset(tables)
        assert "sku_id" in {
            column["name"]
            for column in inspect(connection).get_columns("supplier_products")
        }
        assert "attribute_definition_id" in {
            column["name"]
            for column in inspect(connection).get_columns("product_attributes")
        }
    product_engine.dispose()

    command.downgrade(config, "20260718_0014")
    downgraded_engine = create_engine(migration_url)
    with downgraded_engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert {
            "skus",
            "attribute_definitions",
            "supplier_prices",
            "product_audit_events",
        }.isdisjoint(tables)
    downgraded_engine.dispose()
    command.upgrade(config, "head")
    command.check(config)


def test_product_center_sku_matrix_price_history_attributes_and_audit() -> None:
    product_id = UUID("71000000-0000-0000-0000-000000000002")
    detail_response = client.get(f"/api/v1/products/{product_id}")
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail["product_code"] == "SKU-18211"
    assert detail["sources"]
    category_id = detail["category"]["id"]

    definition_response = client.post(
        "/api/v1/attribute-definitions",
        json={
            "category_id": category_id,
            "attribute_key": f"finish_{uuid4().hex[:8]}",
            "display_name": "表面工艺",
            "data_type": "ENUM",
            "enum_values": ["powder-coated", "galvanized"],
            "is_filterable": True,
            "is_matchable": True,
        },
    )
    assert definition_response.status_code == 201, definition_response.text

    prefix = uuid4().hex[:7].upper()
    sku_items = [
        {
            "sku_code": f"{prefix}-{color}-{size}",
            "name": f"Fence {color} {size}",
            "option_values": {"color": color, "size": size},
            "default_moq": "10",
            "moq_unit": "piece",
            "status": "ACTIVE",
        }
        for color in ("BLACK", "WHITE")
        for size in ("S", "M", "L")
    ]
    sku_response = client.post(
        f"/api/v1/products/{product_id}/skus", json={"items": sku_items}
    )
    assert sku_response.status_code == 201, sku_response.text
    created_skus = sku_response.json()
    assert len(created_skus) == 6

    duplicate = client.post(
        f"/api/v1/products/{product_id}/skus", json={"items": [sku_items[0]]}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "SKU_CODE_CONFLICT"

    first_sku = created_skus[0]
    updated = client.patch(
        f"/api/v1/skus/{first_sku['id']}",
        json={"expected_version": 1, "barcode": f"BC-{prefix}"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    stale = client.patch(
        f"/api/v1/skus/{first_sku['id']}",
        json={"expected_version": 1, "barcode": "STALE"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "SKU_VERSION_CONFLICT"

    exact = client.get("/api/v1/products", params={"q": sku_items[0]["sku_code"]})
    assert exact.status_code == 200
    assert exact.json()[0]["id"] == str(product_id)

    supplier_product_id = detail["sources"][0]["supplier_product_id"]
    now = datetime.now(UTC)
    valid_price = client.post(
        "/api/v1/product-prices",
        json={
            "supplier_product_id": supplier_product_id,
            "sku_id": first_sku["id"],
            "min_quantity": "100",
            "unit_price": "139.50",
            "currency": "cny",
            "unit_code": "piece",
            "valid_from": now.isoformat(),
            "valid_to": (now + timedelta(days=90)).isoformat(),
        },
    )
    assert valid_price.status_code == 201, valid_price.text
    assert valid_price.json()["price_validity"] == "VALID"
    expired_price = client.post(
        "/api/v1/product-prices",
        json={
            "supplier_product_id": supplier_product_id,
            "min_quantity": "500",
            "unit_price": "128",
            "currency": "CNY",
            "unit_code": "piece",
            "valid_from": (now - timedelta(days=120)).isoformat(),
            "valid_to": (now - timedelta(days=30)).isoformat(),
        },
    )
    assert expired_price.status_code == 201, expired_price.text
    assert expired_price.json()["price_validity"] == "EXPIRED"
    history = client.get(f"/api/v1/products/{product_id}/prices")
    assert history.status_code == 200
    assert {valid_price.json()["id"], expired_price.json()["id"]}.issubset(
        {item["id"] for item in history.json()}
    )

    refreshed = client.get(f"/api/v1/products/{product_id}").json()
    actions = {event["action"] for event in refreshed["activity"]}
    assert {"sku.created", "sku.updated", "price.confirmed"}.issubset(actions)

    with SessionLocal() as session:
        hidden = list_authoritative_products(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            permissions=frozenset({"product.view"}),
            query=sku_items[0]["sku_code"],
            category_id=None,
            supplier_id=None,
            statuses=[],
            approved_images_only=False,
            limit=10,
        )
        assert hidden and hidden[0].price is None
        assert hidden[0].current_offer is not None
        assert hidden[0].current_offer.unit_price is None


def test_product_review_queue_uses_candidate_evidence_and_human_adoption() -> None:
    csv_content = (
        "Product Name,Item No,Material,Color,Size,MOQ\n"
        f"Review Queue Product {uuid4().hex[:6]},RQ-{uuid4().hex[:6]},TPR,Blue,10cm,120\n"
    ).encode("utf-8")
    upload = client.post(
        "/api/v1/imports",
        files={"file": ("review-queue.csv", csv_content, "text/csv")},
        data={"supplier_id": "SUP-001", "source_type": "SUPPLIER_CATALOG"},
    )
    assert upload.status_code == 201, upload.text
    assert upload.json()["candidate_status"] == "NEEDS_REVIEW"
    task_id = upload.json()["ai_task_id"]

    queue = client.get("/api/v1/product-review-items", params={"limit": 500})
    assert queue.status_code == 200, queue.text
    item = next(row for row in queue.json() if row["task_id"] == task_id)
    assert item["status"] == "pending"
    assert item["source"].startswith("SRC-")
    assert item["fields"] and all(field["source"] for field in item["fields"])
    confirmed = {field["key"]: field["normalized"] for field in item["fields"]}
    approval = client.post(
        f"/api/v1/ai/product-intelligence/tasks/{task_id}/groups/{item['candidate_group_key']}/approve",
        json={
            "idempotency_key": f"review-ui-{uuid4()}",
            "confirmed_values": confirmed,
            "activate": True,
            "product_code": f"ATC-RQ-{uuid4().hex[:8].upper()}",
            "change_reason": "ACG-009 Product review page acceptance",
        },
    )
    assert approval.status_code == 202, approval.text
    refreshed = client.get("/api/v1/product-review-items", params={"limit": 500})
    reviewed = next(row for row in refreshed.json() if row["task_id"] == task_id)
    assert reviewed["status"] == "approved"
    assert reviewed["applied_product_id"] == approval.json()["product_id"]


def test_image_intelligence_projection_search_and_media_gate(tmp_path: Path) -> None:
    product_id = UUID("71000000-0000-0000-0000-000000000002")
    image_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    image_id = uuid4()
    object_key = f"tenants/{DEFAULT_TENANT_ID}/source/product-images/{image_id}.png"
    path = tmp_path / "approved-product.png"
    path.write_bytes(image_bytes)
    get_object_storage().put_file(path, object_key=object_key, content_type="image/png")
    with SessionLocal() as session:
        session.add(ProductImageRow(id=image_id, tenant_id=DEFAULT_TENANT_ID, product_id=product_id, storage_provider="local", bucket="local", object_key=object_key, original_filename=path.name, content_type="image/png", byte_size=len(image_bytes), sha256=image_hash, width=1, height=1, image_role="MAIN", sort_order=99, approval_status="APPROVED"))
        source_id = uuid4()
        session.add(ProductImageRow(id=source_id, tenant_id=DEFAULT_TENANT_ID, product_id=product_id, storage_provider="local", bucket="local", object_key=f"source/{source_id}.png", original_filename="source.png", content_type="image/png", byte_size=len(image_bytes), sha256=image_hash, width=1, height=1, image_role="GALLERY", sort_order=100, approval_status="SOURCE"))
        session.commit()

    projection = client.post(f"/api/v1/product-images/{image_id}/intelligence")
    assert projection.status_code == 200, projection.text
    assert projection.json()["idempotent"] is False
    repeated = client.post(f"/api/v1/product-images/{image_id}/intelligence")
    assert repeated.status_code == 200
    assert repeated.json()["idempotent"] is True
    assert repeated.json()["embedding_id"] == projection.json()["embedding_id"]
    rejected = client.post(f"/api/v1/product-images/{source_id}/intelligence")
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "IMAGE_NOT_APPROVED"

    search = client.post("/api/v1/image-searches?limit=5", files={"file": ("query.png", image_bytes, "image/png")})
    assert search.status_code == 200, search.text
    payload = search.json()
    assert payload["status"] == "COMPLETED"
    assert payload["results"][0]["product_id"] == str(product_id)
    assert payload["results"][0]["classification"] == "POSSIBLE_SAME_ITEM"
    assert "never proves" in payload["warnings"][0]
    with SessionLocal() as session:
        expired_search = session.get(ImageSearchRow, UUID(payload["id"]))
        assert expired_search is not None
        expired_search.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        expired_key = expired_search.query_object_key
        session.commit()
    assert get_object_storage().local_path(expired_key).is_file()
    cleanup_trigger = client.post("/api/v1/image-searches", files={"file": ("query-2.png", image_bytes, "image/png")})
    assert cleanup_trigger.status_code == 200
    with SessionLocal() as session:
        expired_search = session.get(ImageSearchRow, UUID(payload["id"]))
        assert expired_search.status == "EXPIRED"
        assert expired_search.query_embedding is None
    assert not get_object_storage().local_path(expired_key).exists()
    malware = client.post("/api/v1/image-searches", files={"file": ("evil.png", image_bytes + b"ATC-MALWARE-TEST", "image/png")})
    assert malware.status_code == 403
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(ImageEmbeddingRow).where(ImageEmbeddingRow.product_image_id == image_id)) == 1
        assert session.scalar(select(func.count()).select_from(VisionObservationRow).where(VisionObservationRow.product_image_id == image_id)) == 1
        assert session.scalar(select(func.count()).select_from(ImageSearchRow).where(ImageSearchRow.tenant_id == DEFAULT_TENANT_ID)) >= 1
        assert session.get(ProductImageRow, source_id).approval_status == "SOURCE"


def test_development_image_provider_is_fail_closed_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("IMAGE_INTELLIGENCE_PROFILE", "deterministic")
    with pytest.raises(RuntimeError, match="forbidden"):
        get_image_intelligence_provider()


def test_dashboard_and_supplier_profiles_use_tenant_scoped_authoritative_data() -> None:
    dashboard = client.get("/api/v1/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    payload = dashboard.json()
    assert payload["data_scope"] == "TENANT"
    metric_keys = {metric["key"] for metric in payload["metrics"]}
    assert {"active_skus", "today_inquiries", "pending_quotations", "active_suppliers"}.issubset(metric_keys)
    assert payload["data_health"]["active_products"] >= 3
    assert 0 <= payload["data_health"]["score"] <= 100

    directory = client.get("/api/v1/supplier-profiles")
    assert directory.status_code == 200, directory.text
    suppliers = directory.json()
    assert suppliers
    seeded = next(row for row in suppliers if row["id"] == "SUP-001")
    assert seeded["active_products"] >= 1
    assert seeded["active_skus"] >= 1
    assert seeded["valid_prices"] >= 1
    detail = client.get("/api/v1/supplier-profiles/SUP-001")
    assert detail.status_code == 200, detail.text
    assert detail.json()["sources"]
    assert detail.json()["sources"][0]["product_code"]

    other_tenant_id = uuid4()
    other_supplier_id = f"SUP-X-{uuid4().hex[:8]}"
    with SessionLocal() as session:
        session.add(TenantRow(id=other_tenant_id, organization_id=DEFAULT_ORGANIZATION_ID, slug=f"other-{uuid4().hex[:8]}", name="Other isolated tenant"))
        session.flush()
        session.add(SupplierRow(id=other_supplier_id, tenant_id=other_tenant_id, supplier_code=other_supplier_id, name="Must not leak", category="isolated"))
        session.commit()
    isolated_directory = client.get("/api/v1/supplier-profiles")
    assert all(row["id"] != other_supplier_id for row in isolated_directory.json())
    assert client.get(f"/api/v1/supplier-profiles/{other_supplier_id}").status_code == 404


def test_inquiry_matching_selection_and_human_gated_quotation() -> None:
    customer = client.post("/api/v1/customers", json={"company_name": f"ACG Customer {uuid4().hex[:6]}", "country_code": "US", "language": "en", "default_currency": "CNY"})
    assert customer.status_code == 201, customer.text
    inquiry = client.post("/api/v1/inquiries", json={"customer_id": customer.json()["id"], "currency": "CNY", "language": "en", "items": [{"requirement": "SKU-18211", "quantity": 10, "unit_code": "PCS"}]})
    assert inquiry.status_code == 201, inquiry.text
    inquiry_payload = inquiry.json()
    assert inquiry_payload["status"] == "MATCHING"
    item_id = inquiry_payload["items"][0]["id"]

    matched = client.post(f"/api/v1/inquiries/{inquiry_payload['id']}/match")
    assert matched.status_code == 200, matched.text
    candidates = matched.json()["candidates"][item_id]
    assert candidates
    assert candidates[0]["total_score"] == 1.0
    assert "精确产品编码命中" in candidates[0]["reasons"]

    rematched = client.post(f"/api/v1/inquiries/{inquiry_payload['id']}/match")
    assert rematched.status_code == 200, rematched.text
    stale_selection = client.post(f"/api/v1/inquiry-items/{item_id}/selection", json={"match_result_id": candidates[0]["id"]})
    assert stale_selection.status_code == 409
    assert stale_selection.json()["detail"]["code"] == "MATCH_RESULT_STALE"
    candidates = rematched.json()["candidates"][item_id]

    selected = client.post(f"/api/v1/inquiry-items/{item_id}/selection", json={"match_result_id": candidates[0]["id"]})
    assert selected.status_code == 200, selected.text
    assert selected.json()["status"] == "SELECTED"
    ready = client.get(f"/api/v1/inquiries/{inquiry_payload['id']}").json()
    assert ready["status"] == "READY_FOR_QUOTE"

    with SessionLocal() as session:
        selected_product = session.get(ProductRow, UUID(candidates[0]["product_id"]))
        original_version = selected_product.current_version
        selected_product.current_version += 1
        session.commit()
    stale_quote = client.post(f"/api/v1/inquiries/{inquiry_payload['id']}/quotation", json={"target_margin_rate": "0.20", "expires_in_days": 30})
    assert stale_quote.status_code == 409
    assert stale_quote.json()["detail"]["code"] == "MATCH_STALE"
    with SessionLocal() as session:
        selected_product = session.get(ProductRow, UUID(candidates[0]["product_id"]))
        selected_product.current_version = original_version
        session.commit()

    with SessionLocal() as session:
        selected_source = session.get(SupplierProductRow, UUID(candidates[0]["supplier_product_id"]))
        original_source_status = selected_source.status
        selected_source.status = "INACTIVE"
        session.commit()
    inactive_source_quote = client.post(f"/api/v1/inquiries/{inquiry_payload['id']}/quotation", json={"target_margin_rate": "0.20", "expires_in_days": 30})
    assert inactive_source_quote.status_code == 409
    assert inactive_source_quote.json()["detail"]["code"] == "SUPPLIER_SOURCE_MISSING"
    with SessionLocal() as session:
        selected_source = session.get(SupplierProductRow, UUID(candidates[0]["supplier_product_id"]))
        selected_source.status = original_source_status
        session.commit()

    quote = client.post(f"/api/v1/inquiries/{inquiry_payload['id']}/quotation", json={"target_margin_rate": "0.20", "expires_in_days": 30})
    assert quote.status_code == 201, quote.text
    quote_payload = quote.json()
    assert quote_payload["status"] == "CALCULATED"
    assert quote_payload["approval_status"] == "PENDING"
    assert quote_payload["items"][0]["unit_cost"] is not None
    assert Decimal(quote_payload["items"][0]["line_total"]) == Decimal(quote_payload["items"][0]["unit_price"]) * Decimal("10")

    approved = client.post(f"/api/v1/quotations/{quote_payload['id']}/decision", json={"decision": "APPROVED", "reason": "Owner verified customer, source and margin"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["version_hash"] == quote_payload["version_hash"]
    quote_list = client.get("/api/v1/quotations")
    assert quote_list.status_code == 200
    assert any(row["id"] == quote_payload["id"] for row in quote_list.json())
    repeated = client.post(f"/api/v1/quotations/{quote_payload['id']}/decision", json={"decision": "APPROVED", "reason": "duplicate"})
    assert repeated.status_code == 409
    revised = client.post(
        f"/api/v1/quotations/{quote_payload['id']}/revisions",
        json={
            "expected_version": 1,
            "change_reason": "Customer increased the confirmed quantity",
            "items": [{"item_id": quote_payload["items"][0]["id"], "quantity": "20", "target_margin_rate": "0.25"}],
        },
    )
    assert revised.status_code == 201, revised.text
    revised_payload = revised.json()
    assert revised_payload["current_version"] == 2
    assert revised_payload["status"] == "CALCULATED"
    assert revised_payload["approval_status"] == "PENDING"
    assert revised_payload["version_hash"] != quote_payload["version_hash"]
    assert Decimal(revised_payload["items"][0]["quantity"]) == Decimal("20")
    assert len(revised_payload["versions"]) == 2
    assert revised_payload["versions"][0]["version_number"] == 2
    stale_revision = client.post(
        f"/api/v1/quotations/{quote_payload['id']}/revisions",
        json={
            "expected_version": 1,
            "change_reason": "Stale browser must not overwrite",
            "items": [{"item_id": revised_payload["items"][0]["id"], "quantity": "30", "target_margin_rate": "0.25"}],
        },
    )
    assert stale_revision.status_code == 409
    assert stale_revision.json()["detail"]["code"] == "QUOTATION_VERSION_CONFLICT"
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(InquiryRow).where(InquiryRow.id == UUID(inquiry_payload["id"]))) == 1
        assert session.scalar(select(func.count()).select_from(InquiryMatchResultRow).where(InquiryMatchResultRow.inquiry_item_id == UUID(item_id), InquiryMatchResultRow.status == "SELECTED")) == 1
        assert session.scalar(select(func.count()).select_from(QuotationRow).where(QuotationRow.id == UUID(quote_payload["id"]))) == 1
        assert session.scalar(select(func.count()).select_from(QuotationVersionRow).where(QuotationVersionRow.quotation_id == UUID(quote_payload["id"]))) == 2
        assert session.scalar(select(func.count()).select_from(QuotationItemRow).join(QuotationVersionRow, QuotationVersionRow.id == QuotationItemRow.quotation_version_id).where(QuotationVersionRow.quotation_id == UUID(quote_payload["id"]))) == 2
        assert session.scalar(select(func.count()).select_from(QuotationApprovalRow).where(QuotationApprovalRow.quotation_id == UUID(quote_payload["id"]), QuotationApprovalRow.status == "APPROVED")) == 1
        assert session.scalar(select(func.count()).select_from(QuotationApprovalRow).where(QuotationApprovalRow.quotation_id == UUID(quote_payload["id"]), QuotationApprovalRow.status == "PENDING")) == 1
        assert session.scalar(select(func.count()).select_from(OutboxEventRow).where(OutboxEventRow.aggregate_type == "QUOTATION", OutboxEventRow.aggregate_id == quote_payload["id"])) == 3


def test_public_catalog_lists_only_published_active_facts_and_approved_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUBLIC_MEDIA_BASE_URL", "https://cdn.example.test/catalog")

    store_response = client.get("/api/store/demo")
    assert store_response.status_code == 200, store_response.text
    store = store_response.json()
    assert store["slug"] == "demo"
    assert store["name"] == "Local Demo Company"
    assert "待人工确认" in store["quote_notice"]

    listing_response = client.get("/api/store/demo/skus")
    assert listing_response.status_code == 200, listing_response.text
    listing = listing_response.json()
    assert listing["total"] == 3
    by_code = {item["sku_code"]: item for item in listing["items"]}
    assert Decimal(str(by_code["AQ-320S"]["price"])) == Decimal("99.00")
    assert Decimal(str(by_code["PF-8G01"]["price"])) == Decimal("229.00")
    assert Decimal(str(by_code["SF-6L20"]["price"])) == Decimal("299.00")
    assert by_code["AQ-320S"]["image_url"] is None
    assert by_code["SF-6L20"]["image_url"] is None
    assert by_code["PF-8G01"]["image_url"].startswith(
        "https://cdn.example.test/catalog/tenants/"
    )
    for item in listing["items"]:
        assert "unit_cost" not in item
        assert "supplier_product_id" not in item
        assert "supplier_price" not in item

    filtered = client.get(
        "/api/store/demo/skus",
        params={"category": "围栏与玩具", "tags": "宠物围栏"},
    )
    assert filtered.status_code == 200
    assert [item["sku_code"] for item in filtered.json()["items"]] == ["PF-8G01"]

    tag_query = client.get("/api/store/demo/skus", params={"q": "宠物围栏"})
    assert tag_query.status_code == 200
    assert [item["sku_code"] for item in tag_query.json()["items"]] == ["PF-8G01"]

    expanded = client.get(
        "/api/store/demo/skus", params={"q": "围栏 PF", "semantic": "true"}
    )
    assert expanded.status_code == 200
    assert [item["sku_code"] for item in expanded.json()["items"]] == ["PF-8G01"]

    with SessionLocal() as session:
        inactive_sku = session.scalar(select(SkuRow).where(SkuRow.sku_code == "SF-6L20"))
        hidden_product = session.scalar(
            select(ProductRow).where(ProductRow.product_code == "SKU-24018")
        )
        assert inactive_sku is not None and hidden_product is not None
        inactive_sku.status = "INACTIVE"
        hidden_product.status = "DRAFT"
        session.commit()
    try:
        active_only = client.get("/api/store/demo/skus")
        assert active_only.status_code == 200
        assert [item["sku_code"] for item in active_only.json()["items"]] == ["PF-8G01"]
    finally:
        with SessionLocal() as session:
            inactive_sku = session.scalar(select(SkuRow).where(SkuRow.sku_code == "SF-6L20"))
            hidden_product = session.scalar(
                select(ProductRow).where(ProductRow.product_code == "SKU-24018")
            )
            assert inactive_sku is not None and hidden_product is not None
            inactive_sku.status = "ACTIVE"
            hidden_product.status = "ACTIVE"
            session.commit()


def test_public_media_uses_tenant_scoped_relative_proxy_when_no_cdn_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PUBLIC_MEDIA_BASE_URL", raising=False)
    listing = client.get("/api/store/demo/skus", params={"q": "PF-8G01"})
    assert listing.status_code == 200
    image_url = listing.json()["items"][0]["image_url"]
    assert image_url.startswith("/api/store/demo/media/")
    media = client.get(image_url)
    assert media.status_code == 200
    assert media.headers["content-type"].startswith("image/")
    assert media.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/store/demo/media/{uuid4()}").status_code == 404


def test_merchant_publication_requires_active_sku_and_explicit_public_price() -> None:
    product_id = uuid4()
    sku_id = uuid4()
    sku_code = f"PUB-{uuid4().hex[:10].upper()}"
    now = datetime.now(UTC)
    with SessionLocal() as session:
        supplier = session.scalar(
            select(SupplierRow).where(
                SupplierRow.tenant_id == DEFAULT_TENANT_ID,
                SupplierRow.status == "ACTIVE",
            )
        )
        assert supplier is not None
        session.add(
            ProductRow(
                id=product_id,
                tenant_id=DEFAULT_TENANT_ID,
                product_code=sku_code,
                name="Explicit Public Price Product",
                status="ACTIVE",
                default_unit="piece",
            )
        )
        session.flush()
        session.add(
            SkuRow(
                id=sku_id,
                tenant_id=DEFAULT_TENANT_ID,
                product_id=product_id,
                sku_code=sku_code,
                name="Explicit Public Price SKU",
                default_moq=Decimal("2"),
                moq_unit="piece",
                status="DRAFT",
            )
        )
        session.flush()
        source = SupplierProductRow(
            tenant_id=DEFAULT_TENANT_ID,
            supplier_id=supplier.id,
            product_id=product_id,
            sku_id=sku_id,
            supplier_sku=sku_code,
            supplier_product_name="Supplier Private Name",
            status="ACTIVE",
        )
        session.add(source)
        session.flush()
        session.add(
            SupplierPriceRow(
                tenant_id=DEFAULT_TENANT_ID,
                supplier_product_id=source.id,
                sku_id=sku_id,
                min_quantity=Decimal("2"),
                unit_price=Decimal("12.34"),
                currency="CNY",
                unit_code="piece",
                valid_from=now,
                status="CONFIRMED",
                confirmed_by_membership_id=DEFAULT_MEMBERSHIP_ID,
                confirmed_at=now,
            )
        )
        session.commit()

        with pytest.raises(ApplicationError) as denied:
            upsert_public_offer_use_case(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                membership_id=DEFAULT_MEMBERSHIP_ID,
                permissions=frozenset({"product.edit"}),
                sku_id=sku_id,
                request=PublicCatalogOfferUpsertRequest(
                    unit_price=Decimal("88.00"),
                    currency="CNY",
                    tags=["公开标签"],
                    publication_status="PUBLISHED",
                ),
            )
        assert denied.value.code == "PERMISSION_REQUIRED"

    missing_price = client.put(
        f"/api/v1/skus/{sku_id}/public-offer",
        json={"currency": "CNY", "tags": ["公开标签"], "publication_status": "PUBLISHED"},
    )
    assert missing_price.status_code == 422

    inactive = client.put(
        f"/api/v1/skus/{sku_id}/public-offer",
        json={
            "unit_price": "88.00",
            "currency": "cny",
            "tags": ["公开标签", "公开标签"],
            "publication_status": "PUBLISHED",
        },
    )
    assert inactive.status_code == 409
    assert inactive.json()["detail"]["code"] == "PUBLIC_SKU_NOT_ACTIVE"

    activated = client.patch(
        f"/api/v1/skus/{sku_id}",
        json={"expected_version": 1, "status": "ACTIVE"},
    )
    assert activated.status_code == 200, activated.text

    published = client.put(
        f"/api/v1/skus/{sku_id}/public-offer",
        json={
            "unit_price": "88.00",
            "currency": "cny",
            "tags": ["公开标签", "新品"],
            "publication_status": "PUBLISHED",
        },
    )
    assert published.status_code == 200, published.text
    assert Decimal(str(published.json()["unit_price"])) == Decimal("88.00")
    assert published.json()["currency"] == "CNY"
    assert published.json()["publication_status"] == "PUBLISHED"

    offers = client.get(f"/api/v1/products/{product_id}/public-offers")
    assert offers.status_code == 200
    assert len(offers.json()) == 1
    assert "supplier_product_id" not in offers.json()[0]
    assert "unit_cost" not in offers.json()[0]

    public_listing = client.get("/api/store/demo/skus", params={"q": sku_code})
    assert public_listing.status_code == 200
    public_item = public_listing.json()["items"][0]
    assert Decimal(str(public_item["price"])) == Decimal("88.00")
    assert Decimal(str(public_item["price"])) != Decimal("12.34")
    assert "supplier_product_id" not in public_item

    suspended = client.put(
        f"/api/v1/skus/{sku_id}/public-offer",
        json={
            "unit_price": "88.00",
            "currency": "CNY",
            "tags": ["公开标签", "新品"],
            "publication_status": "SUSPENDED",
        },
    )
    assert suspended.status_code == 200
    assert client.get("/api/store/demo/skus", params={"q": sku_code}).json()["total"] == 0

    with SessionLocal() as session:
        audit = session.scalar(
            select(ProductAuditEventRow)
            .where(
                ProductAuditEventRow.tenant_id == DEFAULT_TENANT_ID,
                ProductAuditEventRow.product_id == product_id,
                ProductAuditEventRow.action == "public_offer.published",
            )
            .order_by(ProductAuditEventRow.occurred_at.desc())
        )
        assert audit is not None
        assert audit.after["unit_price"] == "88.00"


def test_supplier_catalog_import_requires_a_tenant_scoped_supplier() -> None:
    response = client.post(
        "/api/v1/imports",
        files={"file": ("unbound.csv", b"name,sku,moq\nUnbound,UB-1,10\n", "text/csv")},
        data={"source_type": "SUPPLIER_CATALOG"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SUPPLIER_REQUIRED"


def test_supplier_manage_creates_unique_tenant_supplier_before_import() -> None:
    suffix = uuid4().hex[:10].upper()
    supplier_code = f"NEW-{suffix}"
    supplier_name = f"New Tenant Supplier {suffix}"
    request = SupplierCreateRequest(
        supplier_code=supplier_code.lower(),
        name=supplier_name,
        category="家居用品",
        country_code="cn",
        website="https://supplier.example.test",
    )
    with SessionLocal() as session:
        with pytest.raises(ApplicationError) as denied:
            create_supplier_use_case(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                permissions=frozenset({"supplier.view"}),
                request=request,
            )
        assert denied.value.code == "PERMISSION_DENIED"

    created = client.post(
        "/api/v1/supplier-profiles", json=request.model_dump(mode="json")
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["supplier_code"] == supplier_code
    assert payload["name"] == supplier_name
    assert payload["country_code"] == "CN"
    assert payload["active_products"] == 0
    assert payload["active_skus"] == 0

    duplicate_code = client.post(
        "/api/v1/supplier-profiles",
        json={**request.model_dump(mode="json"), "name": f"Different {supplier_name}"},
    )
    assert duplicate_code.status_code == 409
    assert duplicate_code.json()["detail"]["code"] == "SUPPLIER_CODE_CONFLICT"

    duplicate_name = client.post(
        "/api/v1/supplier-profiles",
        json={**request.model_dump(mode="json"), "supplier_code": f"ALT-{suffix}"},
    )
    assert duplicate_name.status_code == 409
    assert duplicate_name.json()["detail"]["code"] == "SUPPLIER_NAME_CONFLICT"

    other_organization_id = uuid4()
    other_tenant_id = uuid4()
    with SessionLocal() as session:
        session.add(
            OrganizationRow(
                id=other_organization_id,
                code=f"SUP-{suffix}",
                name=f"Supplier Test Organization {suffix}",
            )
        )
        session.flush()
        session.add(
            TenantRow(
                id=other_tenant_id,
                organization_id=other_organization_id,
                slug=f"supplier-{suffix.casefold()}",
                name=f"Supplier Test Tenant {suffix}",
            )
        )
        session.commit()
        other = create_supplier_use_case(
            session,
            tenant_id=other_tenant_id,
            permissions=frozenset({"supplier.manage"}),
            request=request,
        )
        assert other.supplier_code == supplier_code
        assert other.id != payload["id"]

    current_directory = client.get("/api/v1/supplier-profiles")
    assert current_directory.status_code == 200
    matching = [
        row for row in current_directory.json() if row["supplier_code"] == supplier_code
    ]
    assert [row["id"] for row in matching] == [payload["id"]]


def test_public_quote_draft_snapshot_hashed_expiring_downloads_and_formula_safety() -> None:
    listing = client.get("/api/store/demo/skus", params={"q": "PF-8G01"})
    assert listing.status_code == 200
    sku_data = listing.json()["items"][0]
    original_name = sku_data["name"]
    original_price = Decimal(str(sku_data["price"]))

    create_response = client.post(
        "/api/store/demo/quotes",
        json={
            "customer_name": "=2+2",
            "customer_company": "+Formula Company",
            "customer_email": "buyer@example.test",
            "customer_phone": "@PHONE",
            "notes": "@SUM(A1:A2)",
            "items": [{"sku_id": sku_data["id"], "quantity": 2}],
        },
    )
    assert create_response.status_code == 201, create_response.text
    draft = create_response.json()
    assert draft["status"] == "PENDING_CONFIRMATION"
    assert draft["quote_number"].startswith("QD-")
    assert "不构成" in draft["disclaimer"]
    assert Decimal(str(draft["total"])) == original_price * 2
    raw_token = draft["download_token"]
    assert raw_token and raw_token.startswith(f"{DEFAULT_TENANT_ID}.")
    quote_id = UUID(draft["id"])

    with SessionLocal() as session:
        stored = session.scalar(
            select(PublicQuoteDownloadTokenRow).where(
                PublicQuoteDownloadTokenRow.quote_draft_id == quote_id
            )
        )
        snapshot_item = session.scalar(
            select(PublicQuoteDraftItemRow).where(
                PublicQuoteDraftItemRow.quote_draft_id == quote_id
            )
        )
        stored_draft = session.get(PublicQuoteDraftRow, quote_id)
        assert stored is not None and snapshot_item is not None and stored_draft is not None
        assert stored.token_hash == hash_secret(raw_token)
        assert stored.token_hash != raw_token
        assert len(stored.token_hash) == 64
        assert snapshot_item.name_snapshot == original_name
        assert snapshot_item.unit_price_snapshot == original_price
        assert stored_draft.snapshot["status"] == "PENDING_CONFIRMATION"

        sku = session.get(SkuRow, UUID(sku_data["id"]))
        offer = session.scalar(
            select(PublicCatalogOfferRow).where(
                PublicCatalogOfferRow.sku_id == UUID(sku_data["id"])
            )
        )
        assert sku is not None and offer is not None
        sku.name = "MUTATED AFTER SUBMISSION"
        offer.unit_price = Decimal("9999.00")
        session.commit()
    try:
        pdf_response = client.get(draft["pdf_url"])
        assert pdf_response.status_code == 200, pdf_response.text
        assert pdf_response.content.startswith(b"%PDF")
        assert pdf_response.headers["x-quote-status"] == "PENDING_CONFIRMATION"
        assert "PENDING-CONFIRMATION.pdf" in pdf_response.headers["content-disposition"]

        xlsx_response = client.get(draft["xlsx_url"])
        assert xlsx_response.status_code == 200, xlsx_response.text
        workbook = load_workbook(BytesIO(xlsx_response.content), data_only=False)
        sheet = workbook.active
        assert "待人工确认" in sheet["A1"].value
        assert sheet["B4"].value == "'=2+2"
        header_row = next(
            row_index
            for row_index in range(1, sheet.max_row + 1)
            if sheet.cell(row_index, 1).value == "序号"
        )
        assert sheet.cell(header_row + 1, 3).value == original_name
        assert Decimal(str(sheet.cell(header_row + 1, 6).value)) == original_price
        assert all(cell.data_type != "f" for row in sheet.iter_rows() for cell in row)

        merchant_list = client.get("/api/v1/public-quote-drafts")
        assert merchant_list.status_code == 200
        assert str(quote_id) in {item["id"] for item in merchant_list.json()}
        merchant_detail = client.get(f"/api/v1/public-quote-drafts/{quote_id}")
        assert merchant_detail.status_code == 200
        assert merchant_detail.json()["download_token"] is None
        assert merchant_detail.json()["pdf_url"] is None
        assert merchant_detail.json()["items"][0]["name_snapshot"] == original_name
    finally:
        with SessionLocal() as session:
            sku = session.get(SkuRow, UUID(sku_data["id"]))
            offer = session.scalar(
                select(PublicCatalogOfferRow).where(
                    PublicCatalogOfferRow.sku_id == UUID(sku_data["id"])
                )
            )
            assert sku is not None and offer is not None
            sku.name = original_name
            offer.unit_price = original_price
            session.commit()

    forged_tenant_token = f"{uuid4()}.{raw_token.split('.', 1)[1]}"
    assert client.get(
        f"/api/quotes/{quote_id}/pdf", params={"token": forged_tenant_token}
    ).status_code == 404

    with SessionLocal() as session:
        stored = session.scalar(
            select(PublicQuoteDownloadTokenRow).where(
                PublicQuoteDownloadTokenRow.quote_draft_id == quote_id
            )
        )
        assert stored is not None
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    expired = client.get(f"/api/quotes/{quote_id}/pdf", params={"token": raw_token})
    assert expired.status_code == 410
    assert expired.json()["detail"]["code"] == "DOWNLOAD_EXPIRED"


def test_public_quote_drafts_are_tenant_scoped_for_public_and_authenticated_reads() -> None:
    organization_id = uuid4()
    tenant_b = uuid4()
    product_b = uuid4()
    sku_b = uuid4()
    draft_b = uuid4()
    now = datetime.now(UTC)
    with SessionLocal() as session:
        session.add(
            OrganizationRow(
                id=organization_id,
                code=f"PUBLIC-{organization_id.hex[:8]}",
                name="Public Draft Tenant B Organization",
            )
        )
        session.flush()
        session.add(
            TenantRow(
                id=tenant_b,
                organization_id=organization_id,
                slug=f"public-{tenant_b.hex[:8]}",
                name="Public Draft Tenant B",
            )
        )
        session.flush()
        session.add(
            ProductRow(
                id=product_b,
                tenant_id=tenant_b,
                product_code=f"PB-{product_b.hex[:8]}",
                name="Tenant B Private Product",
                status="ACTIVE",
            )
        )
        session.flush()
        session.add(
            SkuRow(
                id=sku_b,
                tenant_id=tenant_b,
                product_id=product_b,
                sku_code=f"SB-{sku_b.hex[:8]}",
                name="Tenant B Private SKU",
                default_moq=Decimal("1"),
                moq_unit="piece",
                status="ACTIVE",
            )
        )
        session.add(
            PublicQuoteDraftRow(
                id=draft_b,
                tenant_id=tenant_b,
                request_number=f"QD-B-{draft_b.hex[:8]}",
                status="PENDING_CONFIRMATION",
                customer_name="Tenant B Customer",
                currency="CNY",
                subtotal_amount=Decimal("10.00"),
                estimated_total=Decimal("10.00"),
                expires_at=now + timedelta(days=7),
                snapshot={"status": "PENDING_CONFIRMATION", "items": []},
                content_hash="b" * 64,
                disclaimer_version="public-draft-v1",
            )
        )
        session.commit()

    cross_tenant_cart = client.post(
        "/api/store/demo/quotes",
        json={
            "customer_name": "Cross Tenant Attempt",
            "items": [{"sku_id": str(sku_b), "quantity": 1}],
        },
    )
    assert cross_tenant_cart.status_code == 422
    assert cross_tenant_cart.json()["detail"]["code"] == "PUBLIC_SKU_NOT_FOUND"

    merchant_list = client.get("/api/v1/public-quote-drafts")
    assert merchant_list.status_code == 200
    assert str(draft_b) not in {item["id"] for item in merchant_list.json()}
    merchant_detail = client.get(f"/api/v1/public-quote-drafts/{draft_b}")
    assert merchant_detail.status_code == 404


def test_public_catalog_migration_is_reversible_on_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "public-catalog-migration.db"
    migration_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", migration_url)
    public_tables = {
        "tenant_public_profiles",
        "public_catalog_offers",
        "public_quote_drafts",
        "public_quote_draft_items",
        "public_quote_download_tokens",
    }

    command.upgrade(config, "20260718_0019")
    before_engine = create_engine(migration_url)
    assert public_tables.isdisjoint(inspect(before_engine).get_table_names())
    before_engine.dispose()

    command.upgrade(config, "head")
    upgraded_engine = create_engine(migration_url)
    assert public_tables.issubset(inspect(upgraded_engine).get_table_names())
    with upgraded_engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar() == "20260720_0021"
    upgraded_engine.dispose()
    command.check(config)

    command.downgrade(config, "20260718_0019")
    downgraded_engine = create_engine(migration_url)
    assert public_tables.isdisjoint(inspect(downgraded_engine).get_table_names())
    downgraded_engine.dispose()
    command.upgrade(config, "head")
    command.check(config)
