"""Create the local/CI PostgreSQL role boundary before Alembic runs.

This command is intentionally limited to role/database/schema bootstrap. Runtime
table grants are applied after migrations by ``grant_runtime_roles``.
"""

from __future__ import annotations

import json
import os
import re
from typing import Final

import psycopg
from psycopg import sql


ROLE_NAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
ROLE_ENVIRONMENTS: Final = {
    "migration": ("ATC_MIGRATION_DB_ROLE", "atc_migration", "ATC_MIGRATION_DB_PASSWORD"),
    "application": ("ATC_APP_DB_ROLE", "atc_app", "ATC_APP_DB_PASSWORD"),
    "identity": ("ATC_AUTH_DB_ROLE", "atc_auth", "ATC_AUTH_DB_PASSWORD"),
    "worker": ("ATC_WORKER_DB_ROLE", "atc_worker", "ATC_WORKER_DB_PASSWORD"),
    "scheduler": (
        "ATC_SCHEDULER_DB_ROLE",
        "atc_scheduler",
        "ATC_SCHEDULER_DB_PASSWORD",
    ),
}


def validated_role_name(value: str) -> str:
    if not ROLE_NAME_PATTERN.fullmatch(value):
        raise ValueError(f"invalid PostgreSQL role name: {value!r}")
    return value


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _psycopg_url(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _roles() -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for purpose, (role_env, default_role, password_env) in ROLE_ENVIRONMENTS.items():
        result[purpose] = (
            validated_role_name(os.getenv(role_env, default_role)),
            _required(password_env),
        )
    return result


def bootstrap_postgres_roles() -> dict[str, object]:
    admin_url = _required("ATC_POSTGRES_ADMIN_URL")
    roles = _roles()
    with psycopg.connect(_psycopg_url(admin_url), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            database_name = str(cursor.fetchone()[0])
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")

            for purpose, (role_name, password) in roles.items():
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,))
                if cursor.fetchone() is None:
                    cursor.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role_name)))
                # Identity validates memberships and the scheduler discovers
                # active tenant IDs before either can bind a tenant context.
                # Their table grants remain deliberately narrow.
                bypass = (
                    sql.SQL("BYPASSRLS")
                    if purpose in {"identity", "scheduler"}
                    else sql.SQL("NOBYPASSRLS")
                )
                cursor.execute(
                    sql.SQL(
                        "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOINHERIT {} PASSWORD {}"
                    ).format(sql.Identifier(role_name), bypass, sql.Literal(password))
                )

            migration_role = roles["migration"][0]
            runtime_roles = [
                roles[key][0]
                for key in ("application", "identity", "worker", "scheduler")
            ]
            cursor.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                    sql.Identifier(database_name), sql.Identifier(migration_role)
                )
            )
            cursor.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(database_name)
                )
            )
            cursor.execute(
                sql.SQL("GRANT ALL ON DATABASE {} TO {}").format(
                    sql.Identifier(database_name), sql.Identifier(migration_role)
                )
            )
            cursor.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            cursor.execute(
                sql.SQL("ALTER SCHEMA public OWNER TO {}").format(
                    sql.Identifier(migration_role)
                )
            )
            cursor.execute(
                sql.SQL("GRANT ALL ON SCHEMA public TO {}").format(
                    sql.Identifier(migration_role)
                )
            )
            for role_name in runtime_roles:
                cursor.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(database_name), sql.Identifier(role_name)
                    )
                )
                cursor.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                        sql.Identifier(role_name)
                    )
                )

    return {
        "status": "completed",
        "database": database_name,
        "vector_extension": "present",
        "roles": {
            purpose: {
                "name": role_name,
                "superuser": False,
                "bypass_rls": purpose in {"identity", "scheduler"},
            }
            for purpose, (role_name, _password) in roles.items()
        },
    }


def main() -> None:
    print(json.dumps(bootstrap_postgres_roles(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
