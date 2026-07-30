"""Real PostgreSQL/pgvector and non-owner tenant-RLS conformance matrix.

The caller must provision a migrated database and provide two URLs:

* ATC_POSTGRES_OWNER_URL: table-owning migration role (NOBYPASSRLS)
* ATC_POSTGRES_APP_URL: non-owner application role (NOBYPASSRLS)

The script never prints either URL and refuses to count a superuser, BYPASSRLS
role, or table owner as application-role evidence.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError


EXPECTED_HEAD = "20260730_0044"
EXPECTED_POSTGRES_MAJOR = 16
EXPECTED_INDEXES = {
    "ix_embeddings_phase3b_hnsw_384",
    "ix_image_embeddings_hnsw_384",
    "ix_knowledge_chunks_content_fts",
}
ORG_A = UUID("10000000-0000-0000-0000-000000000001")
ORG_B = UUID("10000000-0000-0000-0000-000000000002")
TENANT_A = UUID("20000000-0000-0000-0000-000000000001")
TENANT_B = UUID("20000000-0000-0000-0000-000000000002")
USER_A = UUID("40000000-0000-0000-0000-000000000001")
USER_B = UUID("40000000-0000-0000-0000-000000000002")
TASK_A = UUID("30000000-0000-0000-0000-000000000001")
TASK_B = UUID("30000000-0000-0000-0000-000000000002")
ROLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$-]*$")


def _set_context(connection: Any, *, organization_id: UUID, tenant_id: UUID, user_id: UUID) -> None:
    connection.execute(
        text(
            "SELECT "
            "set_config('app.current_organization_id', :organization_id, true), "
            "set_config('app.current_tenant_id', :tenant_id, true), "
            "set_config('app.current_user_id', :user_id, true)"
        ),
        {
            "organization_id": str(organization_id),
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
        },
    )


def _seed_tenant(connection: Any, *, organization_id: UUID, tenant_id: UUID, task_id: UUID, suffix: str) -> None:
    user_id = USER_A if tenant_id == TENANT_A else USER_B
    _set_context(
        connection,
        organization_id=organization_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    connection.execute(
        text(
            "INSERT INTO organizations (id, code, name, status) "
            "VALUES (:id, :code, :name, 'active') "
            "ON CONFLICT (id) DO UPDATE SET code = EXCLUDED.code, name = EXCLUDED.name"
        ),
        {"id": organization_id, "code": f"RLS-ORG-{suffix}", "name": f"RLS Organization {suffix}"},
    )
    connection.execute(
        text(
            "INSERT INTO tenants "
            "(id, organization_id, slug, name, default_locale, default_currency, timezone, status) "
            "VALUES (:id, :organization_id, :slug, :name, 'en', 'USD', 'UTC', 'active') "
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name"
        ),
        {
            "id": tenant_id,
            "organization_id": organization_id,
            "slug": f"rls-tenant-{suffix.lower()}",
            "name": f"RLS Tenant {suffix}",
        },
    )
    connection.execute(
        text(
            "INSERT INTO ai_tasks "
            "(id, tenant_id, task_type, task_version, risk_level, status, priority, progress, "
            "input_schema_version, input_hash, policy_snapshot, budget_snapshot, route_snapshot, "
            "idempotency_key, record_version) "
            "VALUES (:id, :tenant_id, 'RLS_MATRIX', 1, 'L1_ASSISTIVE', 'PENDING', 10, 0, "
            "1, :input_hash, CAST('{}' AS jsonb), CAST('{}' AS jsonb), CAST('{}' AS jsonb), "
            ":idempotency_key, 1) "
            "ON CONFLICT (id) DO UPDATE SET updated_at = CURRENT_TIMESTAMP"
        ),
        {
            "id": task_id,
            "tenant_id": tenant_id,
            "input_hash": suffix.lower() * 64,
            "idempotency_key": f"rls-matrix-{suffix.lower()}",
        },
    )


def _insert_task(connection: Any, *, task_id: UUID, tenant_id: UUID, idempotency_key: str) -> None:
    connection.execute(
        text(
            "INSERT INTO ai_tasks "
            "(id, tenant_id, task_type, task_version, risk_level, status, priority, progress, "
            "input_schema_version, input_hash, policy_snapshot, budget_snapshot, route_snapshot, "
            "idempotency_key, record_version) "
            "VALUES (:id, :tenant_id, 'RLS_MATRIX_WRITE', 1, 'L1_ASSISTIVE', 'PENDING', 10, 0, "
            "1, :input_hash, CAST('{}' AS jsonb), CAST('{}' AS jsonb), CAST('{}' AS jsonb), "
            ":idempotency_key, 1)"
        ),
        {
            "id": task_id,
            "tenant_id": tenant_id,
            "input_hash": task_id.hex + task_id.hex,
            "idempotency_key": idempotency_key,
        },
    )


def _expect_rls_rejection(operation: Any, message: str) -> None:
    try:
        operation()
    except DBAPIError as exc:
        if "row-level security" not in str(exc).lower():
            raise AssertionError(f"{message}: unexpected database error") from exc
    else:
        raise AssertionError(f"{message}: operation unexpectedly succeeded")


def verify_postgres_rls(owner_url: str, app_url: str) -> dict[str, Any]:
    owner_engine: Engine = create_engine(owner_url, pool_pre_ping=True)
    app_engine: Engine = create_engine(app_url, pool_pre_ping=True)
    try:
        with app_engine.connect() as connection:
            app_role = connection.execute(text("SELECT current_user")).scalar_one()
            role = connection.execute(
                text(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
            server_major = int(connection.execute(text("SHOW server_version_num")).scalar_one()) // 10000
        assert ROLE_NAME.fullmatch(app_role), "application role name is not safely quotable"
        assert not role.rolsuper, "application role must not be a superuser"
        assert not role.rolbypassrls, "application role must be NOBYPASSRLS"
        assert server_major == EXPECTED_POSTGRES_MAJOR, (
            f"expected PostgreSQL {EXPECTED_POSTGRES_MAJOR}, got {server_major}"
        )

        quoted_app_role = owner_engine.dialect.identifier_preparer.quote(app_role)
        with owner_engine.begin() as connection:
            connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted_app_role}"))
            connection.execute(
                text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
                    f"TO {quoted_app_role}"
                )
            )
            connection.execute(
                text(f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {quoted_app_role}")
            )
            connection.execute(
                text(
                    f"REVOKE ALL PRIVILEGES ON TABLE auth_sessions, auth_refresh_tokens, "
                    f"local_account_credentials "
                    f"FROM {quoted_app_role}"
                )
            )
            _seed_tenant(
                connection,
                organization_id=ORG_A,
                tenant_id=TENANT_A,
                task_id=TASK_A,
                suffix="A",
            )
            _seed_tenant(
                connection,
                organization_id=ORG_B,
                tenant_id=TENANT_B,
                task_id=TASK_B,
                suffix="B",
            )

        with app_engine.connect() as connection:
            migration_head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            vector_version = connection.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one()
            cosine_distance = float(
                connection.execute(
                    text("SELECT '[1,2,3]'::vector <=> '[1,2,4]'::vector")
                ).scalar_one()
            )
            index_names = set(
                connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' AND indexname = ANY(:names)"
                    ),
                    {"names": sorted(EXPECTED_INDEXES)},
                ).scalars()
            )
            tenant_tables = connection.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                    "pg_get_userbyid(c.relowner) AS owner_name, "
                    "EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid) AS has_policy "
                    "FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                    "AND EXISTS (SELECT 1 FROM information_schema.columns i "
                    "WHERE i.table_schema = 'public' AND i.table_name = c.relname "
                    "AND i.column_name = 'tenant_id') "
                    "ORDER BY c.relname"
                )
            ).mappings().all()
            special_tables = connection.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                    "pg_get_userbyid(c.relowner) AS owner_name, "
                    "EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid) AS has_policy "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname IN ('organizations', 'users')"
                )
            ).mappings().all()

        assert migration_head == EXPECTED_HEAD
        assert vector_version
        assert 0 <= cosine_distance <= 2
        assert index_names == EXPECTED_INDEXES
        assert tenant_tables, "no tenant-owned tables found"
        for table in [*tenant_tables, *special_tables]:
            assert table["relrowsecurity"], f"{table['relname']} does not have RLS enabled"
            assert table["relforcerowsecurity"], f"{table['relname']} does not FORCE RLS"
            assert table["has_policy"], f"{table['relname']} has no RLS policy"
            assert table["owner_name"] != app_role, f"application role owns {table['relname']}"

        with app_engine.begin() as connection:
            no_context_count = connection.execute(
                text("SELECT count(*) FROM ai_tasks WHERE id IN (:task_a, :task_b)"),
                {"task_a": TASK_A, "task_b": TASK_B},
            ).scalar_one()
        assert no_context_count == 0, "no-context query exposed tenant data"

        no_context_task = uuid4()
        _expect_rls_rejection(
            lambda: _run_insert_transaction(
                app_engine,
                task_id=no_context_task,
                tenant_id=TENANT_A,
                idempotency_key=f"rls-no-context-{no_context_task}",
            ),
            "no-context INSERT",
        )

        app_task_a = uuid4()
        with app_engine.begin() as connection:
            _set_context(
                connection,
                organization_id=ORG_A,
                tenant_id=TENANT_A,
                user_id=USER_A,
            )
            visible_a = connection.execute(
                text("SELECT count(*) FROM ai_tasks WHERE id = :id"), {"id": TASK_A}
            ).scalar_one()
            hidden_b = connection.execute(
                text("SELECT count(*) FROM ai_tasks WHERE id = :id"), {"id": TASK_B}
            ).scalar_one()
            updated_b = connection.execute(
                text("UPDATE ai_tasks SET priority = 11 WHERE id = :id"), {"id": TASK_B}
            ).rowcount
            deleted_b = connection.execute(
                text("DELETE FROM ai_tasks WHERE id = :id"), {"id": TASK_B}
            ).rowcount
            _insert_task(
                connection,
                task_id=app_task_a,
                tenant_id=TENANT_A,
                idempotency_key=f"rls-tenant-a-{app_task_a}",
            )
            inserted_a = connection.execute(
                text("SELECT count(*) FROM ai_tasks WHERE id = :id"), {"id": app_task_a}
            ).scalar_one()
            deleted_a = connection.execute(
                text("DELETE FROM ai_tasks WHERE id = :id"), {"id": app_task_a}
            ).rowcount
        assert (visible_a, hidden_b, updated_b, deleted_b, inserted_a, deleted_a) == (1, 0, 0, 0, 1, 1)

        cross_tenant_task = uuid4()
        _expect_rls_rejection(
            lambda: _run_insert_transaction(
                app_engine,
                task_id=cross_tenant_task,
                tenant_id=TENANT_B,
                idempotency_key=f"rls-cross-tenant-{cross_tenant_task}",
                organization_id=ORG_A,
                context_tenant_id=TENANT_A,
                user_id=USER_A,
            ),
            "Tenant A inserting Tenant B row",
        )

        with app_engine.begin() as connection:
            _set_context(
                connection,
                organization_id=ORG_B,
                tenant_id=TENANT_B,
                user_id=USER_B,
            )
            visible_b = connection.execute(
                text("SELECT count(*) FROM ai_tasks WHERE id = :id"), {"id": TASK_B}
            ).scalar_one()
            hidden_a = connection.execute(
                text("SELECT count(*) FROM ai_tasks WHERE id = :id"), {"id": TASK_A}
            ).scalar_one()
        assert (visible_b, hidden_a) == (1, 0)

        try:
            with app_engine.connect() as connection:
                connection.execute(text("SELECT count(*) FROM local_account_credentials"))
        except DBAPIError as exc:
            assert "permission denied" in str(exc).lower()
            auth_secret_tables = "blocked"
        else:
            raise AssertionError("application role can read authentication secret tables")

        return {
            "status": "passed",
            "postgres_major": server_major,
            "migration_head": migration_head,
            "vector_version": vector_version,
            "cosine_distance": cosine_distance,
            "application_role": app_role,
            "application_role_superuser": bool(role.rolsuper),
            "application_role_bypassrls": bool(role.rolbypassrls),
            "tenant_rls_tables_checked": len(tenant_tables),
            "special_rls_tables_checked": len(special_tables),
            "indexes_checked": sorted(index_names),
            "matrix": {
                "no_context_select": "blocked",
                "no_context_insert": "blocked",
                "tenant_a_reads_a": "allowed",
                "tenant_a_reads_b": "blocked",
                "tenant_a_updates_b": "blocked",
                "tenant_a_deletes_b": "blocked",
                "tenant_a_inserts_a": "allowed",
                "tenant_a_inserts_b": "blocked",
                "tenant_b_reads_b": "allowed",
                "tenant_b_reads_a": "blocked",
                "app_reads_auth_secret_tables": auth_secret_tables,
            },
        }
    finally:
        owner_engine.dispose()
        app_engine.dispose()


def _run_insert_transaction(
    engine: Engine,
    *,
    task_id: UUID,
    tenant_id: UUID,
    idempotency_key: str,
    organization_id: UUID | None = None,
    context_tenant_id: UUID | None = None,
    user_id: UUID | None = None,
) -> None:
    with engine.begin() as connection:
        if context_tenant_id is not None:
            _set_context(
                connection,
                organization_id=organization_id or ORG_A,
                tenant_id=context_tenant_id,
                user_id=user_id or USER_A,
            )
        _insert_task(
            connection,
            task_id=task_id,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )


def main() -> None:
    owner_url = os.environ.get("ATC_POSTGRES_OWNER_URL")
    app_url = os.environ.get("ATC_POSTGRES_APP_URL")
    if not owner_url or not app_url:
        raise SystemExit("ATC_POSTGRES_OWNER_URL and ATC_POSTGRES_APP_URL are required")
    print(json.dumps(verify_postgres_rls(owner_url, app_url), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
