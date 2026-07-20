import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

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


def include_object(
    _object: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    if (
        type_ == "index"
        and reflected
        and compare_to is None
        and name in POSTGRESQL_MIGRATION_MANAGED_INDEXES
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
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
        # SQLite is reported as non-transactional DDL by Alembic, while data
        # backfills still open a SQLAlchemy transaction. Commit that unit
        # explicitly so version rows and backfills are not rolled back on close.
        if connection.dialect.name == "sqlite" and connection.in_transaction():
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
