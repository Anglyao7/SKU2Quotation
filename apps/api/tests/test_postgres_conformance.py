import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from scripts.verify_postgres_rls import verify_postgres_rls
from scripts.verify_postgres_worker_role import verify_postgres_worker_role
from scripts.grant_runtime_roles import (
    AUTH_COLUMN_UPDATE_GRANTS,
    AUTH_TABLE_GRANTS,
)


OWNER_URL = os.environ.get("ATC_POSTGRES_OWNER_URL")
APP_URL = os.environ.get("ATC_POSTGRES_APP_URL")
WORKER_URL = os.environ.get("ATC_POSTGRES_WORKER_URL")
AUTH_URL = os.environ.get("ATC_POSTGRES_AUTH_URL")
SCHEDULER_URL = os.environ.get("ATC_POSTGRES_SCHEDULER_URL")
API_ROOT = Path(__file__).resolve().parents[1]


def test_identity_role_has_no_direct_user_or_membership_update_grant() -> None:
    assert AUTH_TABLE_GRANTS["users"] == ("SELECT",)
    assert AUTH_TABLE_GRANTS["memberships"] == ("SELECT",)
    assert AUTH_COLUMN_UPDATE_GRANTS["users"] == ("status", "updated_at")
    assert AUTH_COLUMN_UPDATE_GRANTS["memberships"] == (
        "status",
        "deleted_at",
        "permission_overrides",
        "permission_version",
        "login_identifier",
        "updated_at",
    )


def test_identity_role_has_minimal_customer_subaccount_transaction_grants() -> None:
    assert AUTH_TABLE_GRANTS["customer_account_access_events"] == (
        "SELECT",
        "INSERT",
    )
    for table_name in (
        "subaccount_pricing_policies",
        "subaccount_product_price_overrides",
        "subaccount_sku_price_overrides",
        "subaccount_category_price_overrides",
    ):
        assert AUTH_TABLE_GRANTS[table_name] == ("SELECT", "UPDATE")


@pytest.mark.skipif(
    not SCHEDULER_URL,
    reason="real PostgreSQL scheduler conformance URL is not configured",
)
def test_real_postgres_scheduler_can_only_discover_active_tenant_ids() -> None:
    engine = create_engine(SCHEDULER_URL, pool_pre_ping=True)  # type: ignore[arg-type]
    try:
        with engine.connect() as connection:
            role = connection.execute(
                text(
                    "SELECT rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
            grants = {
                (str(row.column_name), str(row.privilege_type))
                for row in connection.execute(
                    text(
                        "SELECT column_name, privilege_type "
                        "FROM information_schema.column_privileges "
                        "WHERE table_schema = 'public' AND table_name = 'tenants' "
                        "AND grantee = current_user"
                    )
                )
            }
            discovered = connection.execute(
                text(
                    "SELECT id FROM tenants "
                    "WHERE status = 'active' AND deleted_at IS NULL ORDER BY id"
                )
            ).scalars().all()
        assert role.rolsuper is False
        assert role.rolbypassrls is True
        assert grants == {
            ("id", "SELECT"),
            ("status", "SELECT"),
            ("deleted_at", "SELECT"),
        }
        assert discovered

        with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                connection.execute(text("SELECT name FROM tenants LIMIT 1")).all()
        with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                connection.execute(
                    text("UPDATE tenants SET status = status WHERE false")
                )
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not OWNER_URL or not APP_URL,
    reason="real PostgreSQL conformance URLs are not configured",
)
def test_real_postgres_non_owner_rls_matrix() -> None:
    report = verify_postgres_rls(OWNER_URL, APP_URL)  # type: ignore[arg-type]
    assert report["status"] == "passed"
    assert report["application_role_superuser"] is False
    assert report["application_role_bypassrls"] is False
    assert all(value in {"allowed", "blocked"} for value in report["matrix"].values())


@pytest.mark.skipif(
    not OWNER_URL or not WORKER_URL,
    reason="real PostgreSQL worker conformance URLs are not configured",
)
def test_real_postgres_worker_role_rls_matrix() -> None:
    report = verify_postgres_worker_role(OWNER_URL, WORKER_URL)  # type: ignore[arg-type]
    assert report["status"] == "passed"
    assert report["worker_role_superuser"] is False
    assert report["worker_role_bypassrls"] is False
    assert report["worker_owned_tables"] == 0


@pytest.mark.skipif(
    not OWNER_URL or not APP_URL or not AUTH_URL,
    reason="real PostgreSQL OIDC onboarding URLs are not configured",
)
def test_real_postgres_oidc_invitation_onboarding() -> None:
    process = subprocess.run(
        [sys.executable, "-m", "scripts.verify_postgres_oidc_onboarding"],
        cwd=API_ROOT,
        env=os.environ.copy(),
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(process.stdout)
    assert report["status"] == "passed"
    assert report["identity_direct_membership_update"] == "blocked"
    assert report["identity_direct_platform_admin_update"] == "blocked"
    assert report["invitation_binding_function"] == "allowed"
