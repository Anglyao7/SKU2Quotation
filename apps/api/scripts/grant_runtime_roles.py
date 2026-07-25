"""Apply post-migration least-privilege grants to the runtime DB roles."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable

import psycopg
from psycopg import sql

from .bootstrap_postgres_roles import _psycopg_url, validated_role_name


AUTH_SECRET_TABLES = {"auth_refresh_tokens", "auth_sessions"}
MIGRATION_METADATA_TABLES = {"alembic_version"}
AUTH_TABLE_GRANTS: dict[str, tuple[str, ...]] = {
    "users": ("SELECT",),
    "tenants": ("SELECT",),
    "memberships": ("SELECT",),
    "auth_sessions": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "auth_refresh_tokens": ("SELECT", "INSERT", "UPDATE", "DELETE"),
}
WORKER_TABLES = {
    "worker_jobs",
    "media_objects",
    "source_files",
    "import_jobs",
    "review_items",
    "ai_tasks",
    "ai_runs",
    "ai_task_steps",
    "ai_source_evidence",
    "product_field_candidates",
    "outbox_events",
    "inbox_events",
    "products",
    "product_categories",
    "product_attributes",
    "supplier_products",
    "supplier_score",
    "suppliers",
    "knowledge_documents",
    "knowledge_chunks",
    "embeddings",
}


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _role(environment: str, default: str) -> str:
    return validated_role_name(os.getenv(environment, default))


def _grant_tables(
    cursor: psycopg.Cursor[object],
    *,
    role_name: str,
    tables: Iterable[str],
    privileges: tuple[str, ...] = ("SELECT", "INSERT", "UPDATE", "DELETE"),
) -> None:
    privilege_sql = sql.SQL(", ").join(sql.SQL(value) for value in privileges)
    for table_name in sorted(tables):
        cursor.execute(
            sql.SQL("GRANT {} ON TABLE {} TO {}").format(
                privilege_sql,
                sql.Identifier("public", table_name),
                sql.Identifier(role_name),
            )
        )


def grant_runtime_roles() -> dict[str, object]:
    owner_url = _required("ATC_POSTGRES_OWNER_URL")
    app_role = _role("ATC_APP_DB_ROLE", "atc_app")
    auth_role = _role("ATC_AUTH_DB_ROLE", "atc_auth")
    worker_role = _role("ATC_WORKER_DB_ROLE", "atc_worker")
    scheduler_role = _role("ATC_SCHEDULER_DB_ROLE", "atc_scheduler")

    with psycopg.connect(_psycopg_url(owner_url), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )
            all_tables = {str(row[0]) for row in cursor.fetchall()}
            missing_auth = set(AUTH_TABLE_GRANTS) - all_tables
            missing_worker = WORKER_TABLES - all_tables
            if missing_auth or missing_worker:
                raise RuntimeError(
                    "required migrated tables are missing: "
                    f"auth={sorted(missing_auth)}, worker={sorted(missing_worker)}"
                )

            for role_name in (app_role, auth_role, worker_role, scheduler_role):
                cursor.execute(
                    sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(
                        sql.Identifier(role_name)
                    )
                )
                cursor.execute(
                    sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(
                        sql.Identifier(role_name)
                    )
                )
                cursor.execute(
                    sql.SQL("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {}").format(
                        sql.Identifier(role_name)
                    )
                )
                cursor.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                        sql.Identifier(role_name)
                    )
                )

            app_tables = all_tables - AUTH_SECRET_TABLES - MIGRATION_METADATA_TABLES
            _grant_tables(cursor, role_name=app_role, tables=app_tables)
            if "alembic_version" in all_tables:
                _grant_tables(
                    cursor,
                    role_name=app_role,
                    tables=("alembic_version",),
                    privileges=("SELECT",),
                )

            for table_name, privileges in AUTH_TABLE_GRANTS.items():
                _grant_tables(
                    cursor,
                    role_name=auth_role,
                    tables=(table_name,),
                    privileges=privileges,
                )
            cursor.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION "
                    "public.atc_lock_invitation_email(text) TO {}"
                ).format(sql.Identifier(auth_role))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION "
                    "public.atc_bind_oidc_invitation("
                    "uuid, text, text, text, text, uuid[]) TO {}"
                ).format(sql.Identifier(auth_role))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION "
                    "public.atc_touch_user_login(uuid, text, text) TO {}"
                ).format(sql.Identifier(auth_role))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION "
                    "public.atc_invite_tenant_member("
                    "uuid, uuid, uuid, uuid, text, text, text, boolean) TO {}"
                ).format(sql.Identifier(auth_role))
            )
            _grant_tables(cursor, role_name=worker_role, tables=WORKER_TABLES)
            # The BYPASSRLS scheduler can read only the three columns needed to
            # discover active IDs; it cannot inspect tenant profile data.
            # Business work still uses the NOBYPASSRLS worker connection after
            # binding one explicit tenant context.
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT (id, status, deleted_at) "
                    "ON TABLE public.tenants TO {}"
                ).format(sql.Identifier(scheduler_role))
            )

    return {
        "status": "completed",
        "application": {"role": app_role, "table_count": len(app_tables)},
        "identity": {
            "role": auth_role,
            "table_count": len(AUTH_TABLE_GRANTS),
            "business_table_access": "revoked",
        },
        "worker": {"role": worker_role, "table_count": len(WORKER_TABLES)},
        "scheduler": {
            "role": scheduler_role,
            "table_count": 1,
            "access": "tenants_id_status_deleted_at_select_only",
        },
    }


def main() -> None:
    print(json.dumps(grant_runtime_roles(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
