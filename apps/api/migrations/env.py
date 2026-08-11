import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, inspect, pool

from app import db_models  # noqa: F401
from app.database import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The deployment contract uses DATABASE_URL as the runtime source of truth.
# Keep alembic.ini as the local SQLite fallback, but never silently migrate the
# fallback database when an explicit PostgreSQL URL has been supplied.
database_url = os.getenv("DATABASE_URL")
if database_url and config.cmd_opts is not None:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata

# These PostgreSQL-only expression indexes are created by the Phase 3B
# migration with exact operator classes and predicates. They cannot be
# represented portably in the shared SQLite/PostgreSQL ORM metadata, so they
# are verified by the PostgreSQL conformance test instead of autogenerate.
POSTGRESQL_MIGRATION_MANAGED_INDEXES = {
    "ix_embeddings_phase3b_hnsw_384",
    "ix_image_embeddings_hnsw_384",
    "ix_knowledge_chunks_content_fts",
}
POSTGRESQL_MIGRATION_MANAGED_FOREIGN_KEYS = {
    "fk_skus_tenant_supplier",
    "fk_skus_tenant_latest_import_job",
    # SQLite cannot add these composite constraints to established tables
    # without a disruptive table rebuild. The application keeps the same
    # tenant/parent checks, while PostgreSQL receives the database-level FKs.
    "fk_memberships_tenant_parent_membership",
    "fk_public_quote_drafts_tenant_submitter",
    "fk_tenants_identity_code_merchant_identity_profiles",
}
SQLITE_MIGRATION_MANAGED_UNIQUE_OBJECTS = {
    # SQLite represents this named composite unique constraint as an index
    # after the membership batch rebuild. PostgreSQL retains the constraint
    # shape declared by the ORM and migration.
    "uq_memberships_tenant_login_identifier",
}
SQLITE_APPLICATION_MANAGED_CHECKS = {
    # Migration 0037 deliberately leaves this check to the application on
    # SQLite to avoid a second membership-table rebuild. PostgreSQL owns the
    # database check and remains part of strict autogenerate comparison.
    "ck_memberships_account_scope_allowed",
    "ck_tenants_module_access_mode_allowed",
}
_SQLITE_CHECK_NAMES: dict[str, frozenset[str]] = {}


def _sqlite_check_names(table_name: str) -> frozenset[str]:
    cached = _SQLITE_CHECK_NAMES.get(table_name)
    if cached is not None:
        return cached
    connection = getattr(context.get_context(), "connection", None)
    if connection is None:
        return frozenset()
    names = frozenset(
        str(row["name"])
        for row in inspect(connection).get_check_constraints(table_name)
        if row.get("name")
    )
    _SQLITE_CHECK_NAMES[table_name] = names
    return names


def include_object(
    _object: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    dialect_name = context.get_context().dialect.name
    if (
        type_ == "index"
        and reflected
        and compare_to is None
        and name in POSTGRESQL_MIGRATION_MANAGED_INDEXES
    ):
        return False
    if (
        type_ == "foreign_key_constraint"
        and name in POSTGRESQL_MIGRATION_MANAGED_FOREIGN_KEYS
        and dialect_name == "sqlite"
    ):
        return False
    if (
        dialect_name == "sqlite"
        and name in SQLITE_MIGRATION_MANAGED_UNIQUE_OBJECTS
        and type_ in {"index", "unique_constraint"}
    ):
        return False
    if dialect_name == "sqlite" and type_ == "check_constraint" and name:
        if name in SQLITE_APPLICATION_MANAGED_CHECKS:
            return False
        table_name = str(getattr(getattr(_object, "table", None), "name", ""))
        prefix = f"ck_{table_name}_"
        # Historical create_table migrations supplied an already-prefixed
        # check name while the metadata naming convention added the prefix a
        # second time. SQLite reflects that doubled physical name. Treat only
        # this exact legacy pair as equivalent; PostgreSQL and every other
        # check-constraint difference remain visible to autogenerate.
        if reflected and name.startswith(f"{prefix}{prefix}"):
            return False
        if (
            not reflected
            and compare_to is None
            and table_name
            and f"{prefix}{name}" in _sqlite_check_names(table_name)
        ):
            return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        if is_sqlite:
            # Alembic batch mode rebuilds tables for operations SQLite cannot
            # express with ALTER TABLE. Parent tables may already be referenced
            # by live rows, so enforcement must be disabled for the migration
            # connection and verified once the replacement tables are in place.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
            render_as_batch=is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()
        # SQLite is reported as non-transactional DDL by Alembic, while data
        # backfills still open a SQLAlchemy transaction. Commit that unit
        # explicitly so version rows and backfills are not rolled back on close.
        if is_sqlite and connection.in_transaction():
            connection.commit()
        if is_sqlite:
            violations = connection.exec_driver_sql(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if violations:
                raise RuntimeError(
                    "SQLite foreign key violations after migrations: "
                    f"{violations!r}"
                )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
