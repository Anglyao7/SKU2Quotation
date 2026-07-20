from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

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
        ("GET", "/api/v1/review-items"),
        ("POST", "/api/v1/pricing/calculate"),
        ("GET", "/api/v1/ai/product-intelligence/tasks/{task_id}/candidates"),
        ("POST", "/api/v1/ai/knowledge/products/{product_id}/project"),
        ("POST", "/api/v1/ai/search/products"),
        ("POST", "/api/v1/quotations/{quotation_id}/revisions"),
        ("GET", "/api/store/{tenant_slug}"),
        ("GET", "/api/store/{tenant_slug}/skus"),
        ("POST", "/api/store/{tenant_slug}/quotes"),
        ("GET", "/api/quotes/{quote_draft_id}/pdf"),
        ("GET", "/api/quotes/{quote_draft_id}/xlsx"),
        ("GET", "/api/v1/public-quote-drafts"),
        ("GET", "/api/v1/public-quote-drafts/{quote_draft_id}"),
        ("GET", "/api/admin/tenants"),
        ("POST", "/api/admin/tenants"),
        ("PATCH", "/api/admin/tenants/{tenant_id}"),
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
