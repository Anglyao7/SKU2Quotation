import os
from collections.abc import Generator
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker, with_loader_criteria

from .model_mixins import AuditTimestampMixin


API_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = API_ROOT / "var" / "mercator.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
AUTH_DATABASE_URL = os.getenv("AUTH_DATABASE_URL", DATABASE_URL)
ALEMBIC_INI_PATH = API_ROOT / "alembic.ini"

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

if DATABASE_URL.startswith("sqlite"):
    DEFAULT_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)

auth_engine = (
    engine
    if AUTH_DATABASE_URL == DATABASE_URL
    else create_engine(AUTH_DATABASE_URL, pool_pre_ping=True)
)


if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
AuthSessionLocal = sessionmaker(bind=auth_engine, autoflush=False, expire_on_commit=False)


def _postgres_request_context_values(session: Session) -> dict[str, str] | None:
    keys = ("organization_id", "tenant_id", "user_id")
    if not all(session.info.get(key) for key in keys):
        return None
    return {key: str(session.info[key]) for key in keys}


def _bind_postgres_request_context(connection: object, values: dict[str, str]) -> None:
    """Apply trusted RLS values to the PostgreSQL transaction that just began."""
    connection.execute(  # type: ignore[attr-defined]
        text(
            "SELECT "
            "set_config('app.current_organization_id', :organization_id, true), "
            "set_config('app.current_tenant_id', :tenant_id, true), "
            "set_config('app.current_user_id', :user_id, true)"
        ),
        values,
    )


@event.listens_for(Session, "after_begin")
def _restore_request_context_after_begin(
    session: Session,
    _transaction: object,
    connection: object,
) -> None:
    """Rebind transaction-local RLS values after use cases commit mid-request."""
    if connection.dialect.name != "postgresql":  # type: ignore[attr-defined]
        return
    values = _postgres_request_context_values(session)
    if values is not None:
        _bind_postgres_request_context(connection, values)


@event.listens_for(Session, "do_orm_execute")
def _exclude_soft_deleted_rows(execute_state: object) -> None:
    if not execute_state.is_select or execute_state.execution_options.get("include_deleted", False):
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            AuditTimestampMixin,
            lambda model: model.deleted_at.is_(None),
            include_aliases=True,
        )
    )


def run_migrations(revision: str = "head") -> None:
    """Apply Alembic migrations using the already-resolved application URL."""
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
    command.upgrade(config, revision)


def init_database() -> None:
    auto_migrate_default = "true" if DATABASE_URL.startswith("sqlite") else "false"
    auto_migrate = os.getenv("AUTO_MIGRATE", auto_migrate_default).lower() in {"1", "true", "yes"}
    if auto_migrate:
        run_migrations()


def set_request_context(
    session: Session,
    *,
    organization_id: UUID | str,
    tenant_id: UUID | str,
    user_id: UUID | str,
) -> None:
    """Bind the authorization context used by PostgreSQL RLS to this transaction."""
    session.info.update(
        organization_id=str(organization_id),
        tenant_id=str(tenant_id),
        user_id=str(user_id),
    )
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    # If a transaction already exists, bind immediately. Otherwise the
    # ``after_begin`` listener applies the values on the first DB operation.
    if session.in_transaction():
        values = _postgres_request_context_values(session)
        if values is not None:
            _bind_postgres_request_context(session.connection(), values)


def set_public_tenant_context(session: Session, *, tenant_id: UUID | str) -> None:
    """Bind an anonymous published-catalog request to one trusted tenant.

    Zero UUIDs deliberately provide no organization or user visibility while
    keeping the shared transaction rebinding hook fail-closed and type-safe.
    """

    zero_identity = "00000000-0000-0000-0000-000000000000"
    set_request_context(
        session,
        organization_id=zero_identity,
        tenant_id=tenant_id,
        user_id=zero_identity,
    )
    session.info["request_scope"] = "public_catalog"


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def get_auth_session() -> Generator[Session, None, None]:
    """Identity repository session; production may bind a separate privileged role."""
    with AuthSessionLocal() as session:
        yield session
