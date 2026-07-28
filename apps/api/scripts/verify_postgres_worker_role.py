"""Verify the durable worker uses a non-owner, tenant-scoped PostgreSQL role."""

from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


ORG_A = UUID("10000000-0000-0000-0000-000000000001")
ORG_B = UUID("10000000-0000-0000-0000-000000000002")
TENANT_A = UUID("20000000-0000-0000-0000-000000000001")
TENANT_B = UUID("20000000-0000-0000-0000-000000000002")
USER_A = UUID("40000000-0000-0000-0000-000000000001")
USER_B = UUID("40000000-0000-0000-0000-000000000002")
TASK_A = UUID("30000000-0000-0000-0000-000000000001")
TASK_B = UUID("30000000-0000-0000-0000-000000000002")
REQUIRED_TABLES = {
    "worker_jobs",
    "media_objects",
    "source_files",
    "import_jobs",
    "review_items",
    "ai_tasks",
    "ai_runs",
    "ai_task_steps",
    "product_field_candidates",
    "outbox_events",
    "inbox_events",
}


def _set_context(connection: Any, organization_id: UUID, tenant_id: UUID, user_id: UUID) -> None:
    connection.execute(
        text(
            "SELECT set_config('app.current_organization_id', :organization_id, true), "
            "set_config('app.current_tenant_id', :tenant_id, true), "
            "set_config('app.current_user_id', :user_id, true)"
        ),
        {
            "organization_id": str(organization_id),
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
        },
    )


def verify_postgres_worker_role(owner_url: str, worker_url: str) -> dict[str, Any]:
    owner_engine = create_engine(owner_url, pool_pre_ping=True)
    worker_engine = create_engine(worker_url, pool_pre_ping=True)
    try:
        with worker_engine.connect() as connection:
            worker_role = connection.execute(text("SELECT current_user")).scalar_one()
        with owner_engine.connect() as connection:
            role = connection.execute(
                text(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :role"
                ),
                {"role": worker_role},
            ).mappings().one()
            owned_tables = connection.execute(
                text(
                    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relkind='r' "
                    "AND pg_get_userbyid(c.relowner)=:role"
                ),
                {"role": worker_role},
            ).scalar_one()
        assert not role.rolsuper
        assert not role.rolbypassrls
        assert owned_tables == 0

        with worker_engine.connect() as connection:
            granted_tables = {
                table
                for table in REQUIRED_TABLES
                if connection.execute(
                    text("SELECT has_table_privilege(current_user, :table, 'SELECT,INSERT,UPDATE,DELETE')"),
                    {"table": table},
                ).scalar_one()
            }
        assert granted_tables == REQUIRED_TABLES

        with worker_engine.begin() as connection:
            no_context = connection.execute(
                text("SELECT count(*) FROM ai_tasks WHERE id IN (:a, :b)"),
                {"a": TASK_A, "b": TASK_B},
            ).scalar_one()
        assert no_context == 0

        with worker_engine.begin() as connection:
            _set_context(connection, ORG_A, TENANT_A, USER_A)
            tenant_a = connection.execute(
                text("SELECT id FROM ai_tasks WHERE id IN (:a, :b) ORDER BY id"),
                {"a": TASK_A, "b": TASK_B},
            ).scalars().all()
        with worker_engine.begin() as connection:
            _set_context(connection, ORG_B, TENANT_B, USER_B)
            tenant_b = connection.execute(
                text("SELECT id FROM ai_tasks WHERE id IN (:a, :b) ORDER BY id"),
                {"a": TASK_A, "b": TASK_B},
            ).scalars().all()
        assert tenant_a == [TASK_A]
        assert tenant_b == [TASK_B]

        try:
            with worker_engine.connect() as connection:
                connection.execute(text("SELECT count(*) FROM local_account_credentials"))
        except DBAPIError as exc:
            assert "permission denied" in str(exc).lower()
        else:
            raise AssertionError("worker role can read authentication secret tables")

        return {
            "status": "passed",
            "worker_role": worker_role,
            "worker_role_superuser": bool(role.rolsuper),
            "worker_role_bypassrls": bool(role.rolbypassrls),
            "worker_owned_tables": int(owned_tables),
            "required_worker_tables_checked": len(granted_tables),
            "matrix": {
                "no_context_select": "blocked",
                "tenant_a_reads_a": "allowed",
                "tenant_a_reads_b": "blocked",
                "tenant_b_reads_b": "allowed",
                "tenant_b_reads_a": "blocked",
                "worker_reads_auth_secret_tables": "blocked",
            },
        }
    finally:
        owner_engine.dispose()
        worker_engine.dispose()


if __name__ == "__main__":
    owner_url = os.environ.get("ATC_POSTGRES_OWNER_URL")
    worker_url = os.environ.get("ATC_POSTGRES_WORKER_URL")
    if not owner_url or not worker_url:
        raise SystemExit("ATC_POSTGRES_OWNER_URL and ATC_POSTGRES_WORKER_URL are required")
    print(json.dumps(verify_postgres_worker_role(owner_url, worker_url), indent=2, sort_keys=True))
