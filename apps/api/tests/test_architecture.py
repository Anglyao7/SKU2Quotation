from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from app.tenant_slugs import RESERVED_TENANT_SLUGS

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
API_ROOT = APP_ROOT.parent
REPOSITORY_ROOT = API_ROOT.parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_main_is_only_a_composition_root() -> None:
    path = APP_ROOT / "main.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    assert len(source.splitlines()) <= 80
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(decorator, ast.Call)
            or (
                isinstance(decorator, ast.Attribute)
                and decorator.attr in {"get", "post", "put", "patch", "delete"}
            )
            for decorator in node.decorator_list
        )
        for node in ast.walk(tree)
    )
    imports = _imports(path)
    assert not any(
        forbidden in module
        for module in imports
        for forbidden in ("db_models", "identity_models", "product_supplier_models", "sqlalchemy")
    )


def test_router_use_case_repository_dependency_direction() -> None:
    row_model_modules = {
        "db_models",
        "identity_models",
        "ai_data_models",
        "product_intelligence_models",
        "product_supplier_models",
        "knowledge_embedding_models",
    }
    for path in (APP_ROOT / "routers").glob("*.py"):
        imports = _imports(path)
        assert not imports.intersection(row_model_modules), path
        assert "sqlalchemy" not in imports, path
        assert "sqlalchemy.sql" not in imports, path

    for path in (APP_ROOT / "use_cases").glob("*.py"):
        assert not any(module.startswith("fastapi") for module in _imports(path)), path

    for path in (APP_ROOT / "repositories").glob("*.py"):
        imports = _imports(path)
        assert not any(module.startswith("fastapi") for module in imports), path
        assert not any("routers" in module or "use_cases" in module for module in imports), path

    for path in (APP_ROOT / "domain").glob("*.py"):
        imports = _imports(path)
        assert not any(
            module.startswith("fastapi") or module.startswith("sqlalchemy")
            for module in imports
        ), path


def test_composed_routes_preserve_the_public_contract(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.update(
        DATABASE_URL=f"sqlite:///{(tmp_path / 'architecture.db').as_posix()}",
        UPLOAD_DIR=str(tmp_path / "uploads"),
        APP_ENV="test",
        AUTH_PROFILE="local_fake",
        AUTH_TEST_BYPASS="true",
    )
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from app.main import app; print(json.dumps(app.openapi()['paths']))",
        ],
        cwd=API_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    openapi_paths = json.loads(process.stdout)
    routes = {
        (method.upper(), path)
        for path, operations in openapi_paths.items()
        for method in operations
    }
    expected = {
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/health/live"),
        ("GET", "/api/v1/health/ready"),
        ("POST", "/api/v1/auth/login"),
        ("GET", "/api/v1/auth/memberships"),
        ("GET", "/api/v1/me"),
        ("GET", "/api/v1/suppliers"),
        ("GET", "/api/v1/dashboard"),
        ("GET", "/api/v1/supplier-profiles"),
        ("GET", "/api/v1/supplier-profiles/{supplier_id}"),
        ("POST", "/api/v1/imports"),
        ("GET", "/api/v1/import-files"),
        ("POST", "/api/v1/import-files/{source_file_id}/rollback"),
        ("GET", "/api/v1/review-items"),
        ("POST", "/api/v1/pricing/calculate"),
        ("GET", "/api/v1/ai/product-intelligence/tasks/{task_id}/candidates"),
        ("POST", "/api/v1/ai/knowledge/products/{product_id}/project"),
        ("POST", "/api/v1/ai/search/products"),
        ("POST", "/api/v1/quotations/{quotation_id}/revisions"),
        ("GET", "/api/store/{tenant_slug}"),
        ("GET", "/api/store/{tenant_slug}/products"),
        ("GET", "/api/store/{tenant_slug}/products/{product_id}"),
        ("GET", "/api/store/{tenant_slug}/skus"),
        ("POST", "/api/store/{tenant_slug}/quotes"),
        ("GET", "/api/store/{tenant_slug}/visitor/quotes"),
        ("GET", "/api/quotes/{quote_draft_id}/pdf"),
        ("GET", "/api/quotes/{quote_draft_id}/xlsx"),
        ("GET", "/api/v1/public-quote-drafts"),
        ("GET", "/api/v1/public-quote-drafts/{quote_draft_id}"),
        ("POST", "/api/v1/public-quote-drafts/{quote_draft_id}/currency-conversion"),
        ("PATCH", "/api/v1/public-quote-drafts/{quote_draft_id}/status"),
        ("GET", "/api/v1/storefront-orders/statistics"),
        ("GET", "/api/v1/public-quote-drafts/{quote_draft_id}/pdf"),
        ("GET", "/api/v1/public-quote-drafts/{quote_draft_id}/xlsx"),
        ("GET", "/api/admin/tenants"),
        ("GET", "/api/admin/tenants/{tenant_id}"),
        ("GET", "/api/admin/tenants/{tenant_id}/subaccounts/{membership_id}"),
        ("POST", "/api/admin/tenants"),
        ("PATCH", "/api/admin/tenants/{tenant_id}"),
        ("PATCH", "/api/admin/tenants/{tenant_id}/subscription"),
        ("POST", "/api/admin/tenants/{tenant_id}/owner-account"),
        ("POST", "/api/admin/tenants/{tenant_id}/member-invitations"),
    }
    assert expected.issubset(routes)


def test_web_auth_shell_keeps_access_tokens_out_of_persistent_storage() -> None:
    web_source = REPOSITORY_ROOT / "apps" / "web" / "src"
    api_source = (web_source / "api.ts").read_text(encoding="utf-8")
    routing_source = (web_source / "routing.ts").read_text(encoding="utf-8")
    assert "localStorage.setItem('atc_access_token'" not in api_source
    assert "let accessToken: string | undefined" in api_source
    assert "sessionStorage.setItem(CSRF_STORAGE_KEY" in api_source
    for route in (
        "/dashboard",
        "/suppliers",
        "/review",
        "/products",
        "/inquiries",
        "/quotations",
    ):
        assert route in routing_source


def test_reserved_tenant_slugs_cover_every_static_top_level_web_route() -> None:
    app_source = (
        REPOSITORY_ROOT / "apps" / "web" / "src" / "App.tsx"
    ).read_text(encoding="utf-8")
    route_paths = re.findall(r'\bpath:\s*"(/[^"]*)"', app_source)
    static_top_level_routes = {
        segment
        for path in route_paths
        if (segment := path.removeprefix("/").split("/", 1)[0])
        and not segment.startswith(":")
    }
    assert static_top_level_routes <= RESERVED_TENANT_SLUGS
    assert {"api", "assets", "healthz"} <= RESERVED_TENANT_SLUGS


def test_keycloak_provisioning_keeps_secrets_interactive_and_direct_grant_ready() -> None:
    source = (
        API_ROOT / "scripts" / "provision_keycloak_user_interactive.py"
    ).read_text(encoding="utf-8")
    assert "getpass(" in source
    assert "--admin-password" not in source
    assert "--temporary-password" not in source
    assert '"emailVerified": email_verified' in source
    assert '"temporary": False' in source
    assert '["VERIFY_EMAIL"]' in source
    assert '"UPDATE_PASSWORD"' in source
    assert '"CONFIGURE_TOTP"' in source
    assert "BLOCKING_PASSWORD_ACTIONS" in source
    assert "E164_PATTERN" in source
    assert 'parsed.hostname == "keycloak"' in source
    assert "parsed.port == 8080" in source
    assert "password" not in source.partition("def parser()")[2].lower()


def test_member_invitation_migration_has_database_email_race_guard() -> None:
    invitation_source = (
        API_ROOT
        / "migrations"
        / "versions"
        / "20260723_0023_tenant_member_invitations.py"
    ).read_text(encoding="utf-8")
    binding_source = (
        API_ROOT
        / "migrations"
        / "versions"
        / "20260723_0022_oidc_invitation_binding.py"
    ).read_text(encoding="utf-8")
    lock_service_source = (
        APP_ROOT / "services" / "invitation_email_lock.py"
    ).read_text(encoding="utf-8")
    auth_source = (
        APP_ROOT / "services" / "auth" / "service.py"
    ).read_text(encoding="utf-8")
    member_source = (
        APP_ROOT / "services" / "member_invitations.py"
    ).read_text(encoding="utf-8")
    grant_source = (
        API_ROOT / "scripts" / "grant_runtime_roles.py"
    ).read_text(encoding="utf-8")

    assert "CREATE UNIQUE INDEX uq_users_active_normalized_email" in invitation_source
    assert "CREATE OR REPLACE FUNCTION public.atc_lock_invitation_email" in binding_source
    assert "pg_advisory_xact_lock(hashtextextended(v_email, 0))" in binding_source
    assert "PERFORM public.atc_lock_invitation_email(p_email)" in binding_source
    assert "PERFORM public.atc_lock_invitation_email(v_email)" in invitation_source
    assert "public.atc_lock_invitation_email(:normalized_email)" in lock_service_source
    assert "acquire_invitation_email_lock" in auth_source
    assert "acquire_invitation_email_lock" in member_source
    assert "GRANT EXECUTE ON FUNCTION " in grant_source
    assert "public.atc_lock_invitation_email(text)" in grant_source
    assert "SECURITY DEFINER" in invitation_source
    assert "is_platform_admin = TRUE" not in invitation_source

    binding_function = binding_source[
        binding_source.index(
            "CREATE OR REPLACE FUNCTION public.atc_bind_oidc_invitation"
        ) :
    ]
    invitation_function = invitation_source[
        invitation_source.index(
            "CREATE OR REPLACE FUNCTION public.atc_invite_tenant_member"
        ) :
    ]
    activation_function = auth_source[
        auth_source.index("def _activate_verified_invitation") :
        auth_source.index("\ndef login")
    ]
    member_invitation_function = member_source[
        member_source.index("def _postgres_invite") :
        member_source.index("\ndef _sqlite_invite")
    ]
    assert binding_function.index(
        "PERFORM public.atc_lock_invitation_email(p_email)"
    ) < binding_function.index("UPDATE public.users")
    assert invitation_function.index(
        "PERFORM public.atc_lock_invitation_email(v_email)"
    ) < invitation_function.index("SELECT u.is_platform_admin")
    assert activation_function.index(
        "acquire_invitation_email_lock"
    ) < activation_function.index("candidates = session.scalars")
    assert activation_function.index(
        "acquire_invitation_email_lock"
    ) < activation_function.index("invited_pairs = session.execute")
    assert member_invitation_function.index(
        "acquire_invitation_email_lock"
    ) < member_invitation_function.index("users = list")
    invitation_role_source = invitation_source + (
        API_ROOT
        / "migrations"
        / "versions"
        / "20260724_0026_add_viewer_system_role.py"
    ).read_text(encoding="utf-8")
    for role in ("OWNER", "ADMIN", "SALES", "PURCHASING", "VIEWER"):
        assert role in invitation_role_source


def test_postgres_oidc_binding_qualifies_the_tenant_loop_variable() -> None:
    source = (
        API_ROOT
        / "migrations"
        / "versions"
        / "20260723_0025_fix_oidc_invitation_binding.py"
    ).read_text(encoding="utf-8")

    assert "FOREACH v_tenant_id IN ARRAY p_tenant_ids LOOP" in source
    assert "membership.tenant_id = v_tenant_id" in source
    assert "tenant.id = v_tenant_id" in source
    assert "membership.tenant_id = tenant_id" not in source


def test_viewer_migration_reconciles_all_existing_tenants_and_restores_force_rls() -> None:
    source = (
        API_ROOT
        / "migrations"
        / "versions"
        / "20260724_0026_add_viewer_system_role.py"
    ).read_text(encoding="utf-8")

    assert "FOR v_tenant_id IN" in source
    assert "FROM public.tenants" in source
    assert "'VIEWER'" in source
    assert "INSERT INTO public.role_permissions" in source
    assert "custom VIEWER role conflicts with the managed system role" in source
    assert "UPDATE public.role_permissions AS assignment" in source
    assert "AND NOT EXISTS" in source
    for table in ("tenants", "roles", "role_permissions"):
        assert f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY" in source
        assert f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY" in source


def test_viewer_migration_exposes_member_directory_without_widening_user_writes() -> None:
    source = (
        API_ROOT
        / "migrations"
        / "versions"
        / "20260724_0026_add_viewer_system_role.py"
    ).read_text(encoding="utf-8")
    upgrade_policy = source[
        source.index("def _enable_tenant_member_directory_visibility") :
        source.index("\ndef _restore_active_member_user_policy")
    ]
    downgrade_policy = source[
        source.index("def _restore_active_member_user_policy") :
        source.index("\ndef upgrade")
    ]
    upgrade = source[source.index("def upgrade") : source.index("\ndef downgrade")]
    downgrade = source[source.index("def downgrade") :]

    assert "FOR SELECT USING" in upgrade_policy
    assert "membership.status IN ('active', 'invited', 'suspended')" in upgrade_policy
    assert '"users_self_mutation"' in upgrade_policy
    assert "FOR ALL USING ({self_only}) WITH CHECK ({self_only})" in upgrade_policy
    assert "membership.status = 'active'" in downgrade_policy
    assert "FOR ALL USING ({visibility}) WITH CHECK (id = {user_id})" in downgrade_policy
    assert "_enable_tenant_member_directory_visibility()" in upgrade
    assert "_restore_active_member_user_policy()" in downgrade


def test_managed_runtime_fails_before_database_initialization(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.update(
        APP_ENV="production",
        DATABASE_URL=f"sqlite:///{(tmp_path / 'must-not-open.db').as_posix()}",
        AUTH_PROFILE="local_fake",
        AUTO_MIGRATE="true",
        SEED_DEMO_DATA="true",
    )
    process = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=API_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode != 0
    assert "RuntimeConfigurationError" in process.stderr
    assert not (tmp_path / "must-not-open.db").exists()


def test_postgres_rls_context_is_rebound_after_each_transaction() -> None:
    database_source = (APP_ROOT / "database.py").read_text(encoding="utf-8")
    assert '@event.listens_for(Session, "after_begin")' in database_source
    assert "_restore_request_context_after_begin" in database_source
    assert "_bind_postgres_request_context" in database_source
