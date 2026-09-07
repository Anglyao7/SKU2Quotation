"""Regression for the production-only pending-quote UPDATE trigger failure.

Run with ATC_QUOTE_TEST_DATABASE_URL pointing to an isolated PostgreSQL database
whose name starts with atc_quote_test_. Never point this fixture at an app DB.
Only the three quote tables are needed; unrelated catalog/identity foreign keys
are omitted, while real model columns, check/unique constraints and tenant RLS
are retained. Quote writes, confirmation and order snapshots use production code.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import importlib.util
import os
from pathlib import Path
import time
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import (
    CheckConstraint, Column, MetaData, Table, UniqueConstraint,
    create_engine, event, select, text,
)
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import db_models  # noqa: F401 -- register WorkerJobRow's ImportJobRow relationship
from app.public_catalog_models import (
    PublicQuoteDraftItemRow, PublicQuoteDraftRow, StorefrontOrderRecordRow,
)
from app.public_catalog_schemas import (
    PublicQuoteDraftItemsUpdate, PublicQuoteDraftStatusUpdate,
)
from app.use_cases import public_catalog


MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations/versions/20260907_0135_allow_pending_quote_item_edits.py"
spec = importlib.util.spec_from_file_location("pending_quote_item_edits", MIGRATION_PATH)
assert spec is not None and spec.loader is not None
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
ROLE = "atc_quote_test_app_0135"


def migrate(connection, direction="upgrade"):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration, direction)()


def test_sqlite_migration_is_a_noop():
    engine = create_engine("sqlite://")
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, cur, stmt, p, ctx, many: statements.append(stmt))
    try:
        with engine.begin() as connection:
            migrate(connection)
            migrate(connection, "downgrade")
        assert statements == []
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def pg_engine():
    url = os.getenv("ATC_QUOTE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("isolated PostgreSQL quote regression URL is not configured")
    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as connection:
        assert connection.dialect.name == "postgresql"
        database = connection.scalar(text("SELECT current_database()"))
        assert database.startswith("atc_quote_test_"), "Refusing to change a non-test database"
        metadata = MetaData()
        for model in (PublicQuoteDraftRow, PublicQuoteDraftItemRow, StorefrontOrderRecordRow):
            source = model.__table__
            constraints = []
            for constraint in source.constraints:
                if isinstance(constraint, CheckConstraint):
                    constraints.append(CheckConstraint(str(constraint.sqltext), name=constraint.name))
                elif isinstance(constraint, UniqueConstraint):
                    constraints.append(UniqueConstraint(*(c.name for c in constraint.columns), name=constraint.name))
            table = Table(source.name, metadata, *(
                Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable,
                       server_default=c.server_default) for c in source.columns
            ), *constraints)
            table.create(connection, checkfirst=True)
        connection.exec_driver_sql(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN
                    CREATE ROLE {ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS;
                END IF;
            END $$
        """)
        connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
        for name in metadata.tables:
            connection.exec_driver_sql(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
            connection.exec_driver_sql(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
            connection.exec_driver_sql(f"DROP POLICY IF EXISTS quote_test_tenant ON {name}")
            connection.exec_driver_sql(f"""
                CREATE POLICY quote_test_tenant ON {name}
                USING (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid)
            """)
            connection.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO {ROLE}")
        migrate(connection)
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_immutable_public_quote_draft_items ON public_quote_draft_items")
        connection.exec_driver_sql("""
            CREATE TRIGGER trg_immutable_public_quote_draft_items
            BEFORE UPDATE OR DELETE ON public_quote_draft_items
            FOR EACH ROW EXECUTE FUNCTION public.atc_reject_public_quote_draft_item_mutation()
        """)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def quote(pg_engine):
    tenant_id, draft_id, item_id = uuid4(), uuid4(), uuid4()
    with pg_engine.begin() as connection:
        migrate(connection)
    with Session(pg_engine) as session:
        session.add(PublicQuoteDraftRow(
            id=draft_id, tenant_id=tenant_id, request_number=f"QD-{draft_id}",
            customer_name="Quote regression", currency="USD", subtotal_amount=30,
            estimated_total=30, expires_at=datetime.now(UTC) + timedelta(days=7),
            snapshot={"items": []}, content_hash="a" * 64, disclaimer_version="v1",
        ))
        session.add(PublicQuoteDraftItemRow(
            id=item_id, tenant_id=tenant_id, quote_draft_id=draft_id, sku_id=uuid4(),
            position=1, quantity=1, minimum_order_quantity=1,
            product_id_snapshot=uuid4(), product_version=1, sku_version=1,
            sku_code_snapshot="QUOTE-TEST", name_snapshot="Original name",
            unit_code_snapshot="piece", currency_snapshot="USD",
            unit_price_snapshot=30, line_total=30,
        ))
        session.commit()
    return {"tenant_id": tenant_id, "draft_id": draft_id, "item_id": item_id}


def tenant_session(engine, tenant_id):
    session = Session(engine, expire_on_commit=False)

    @event.listens_for(session, "after_begin")
    def bind_tenant(session, transaction, connection):
        connection.exec_driver_sql(f"SET LOCAL ROLE {ROLE}")
        connection.execute(text("SELECT set_config('app.current_tenant_id', :tenant, true)"), {"tenant": str(tenant_id)})

    return session


def test_old_trigger_reproduces_price_failure_and_upgrade_repairs_it(pg_engine, quote):
    with pg_engine.begin() as connection:
        migrate(connection, "downgrade")
    try:
        with tenant_session(pg_engine, quote["tenant_id"]) as session:
            with pytest.raises(DBAPIError, match="snapshots are immutable"):
                session.execute(text("UPDATE public_quote_draft_items SET unit_price_snapshot=60, line_total=60 WHERE id=:item_id"), quote)
            session.rollback()
        with pg_engine.begin() as connection:
            migrate(connection)
            migrate(connection)  # Safe if a release's preparation is rerun.
        with tenant_session(pg_engine, quote["tenant_id"]) as session:
            session.execute(text("UPDATE public_quote_draft_items SET unit_price_snapshot=60, line_total=60 WHERE id=:item_id"), quote)
            session.commit()
            assert session.get(PublicQuoteDraftItemRow, quote["item_id"]).unit_price_snapshot == Decimal("60")
    finally:
        with pg_engine.begin() as connection:
            migrate(connection)


@pytest.mark.parametrize("scope", ["STAFF", "CUSTOMER_SUBACCOUNT"])
def test_edit_then_confirm_preserves_new_price_and_order_snapshot(pg_engine, quote, monkeypatch, scope):
    # Only optional catalog translation enrichment is outside this fixture.
    monkeypatch.setattr(public_catalog.repository, "get_active_tenant", lambda *a, **kw: None)
    membership_id = uuid4()
    if scope == "CUSTOMER_SUBACCOUNT":
        with Session(pg_engine) as session:
            session.get(PublicQuoteDraftRow, quote["draft_id"]).submitted_by_membership_id = membership_id
            session.commit()
    with tenant_session(pg_engine, quote["tenant_id"]) as session:
        kwargs = dict(tenant_id=quote["tenant_id"], quote_draft_id=quote["draft_id"],
                      membership_id=membership_id, account_scope=scope,
                      permissions=frozenset({"quotation.create"}))
        edited = public_catalog.update_tenant_quote_draft_items(session, **kwargs,
            request=PublicQuoteDraftItemsUpdate(items=[{
                "item_id": quote["item_id"], "unit_price": "60", "quantity": "2",
                "name": "Edited name", "description": "Edited description",
                "specification": "Large", "category": "Samples", "unit_code": "set",
            }]))
        assert edited.total == Decimal("120")
        assert edited.items[0].name_snapshot == "Edited name"
        draft = session.get(PublicQuoteDraftRow, quote["draft_id"])
        assert Decimal(draft.snapshot["items"][0]["unit_price"]) == Decimal("60")
        for _ in range(2):
            confirmed = public_catalog.update_tenant_quote_draft_status(session, **kwargs,
                request=PublicQuoteDraftStatusUpdate(status="CONFIRMED"))
            assert confirmed.status == "CONFIRMED"
            assert confirmed.total == Decimal("120")
        records = session.scalars(select(StorefrontOrderRecordRow).where(
            StorefrontOrderRecordRow.source_quote_draft_id == quote["draft_id"])).all()
        assert len(records) == 1
        assert records[0].submitted_by_membership_id == (membership_id if scope == "CUSTOMER_SUBACCOUNT" else None)
        assert records[0].total_quantity == Decimal("2")
        assert records[0].total_amount == Decimal("120")
        assert Decimal(records[0].snapshot["items"][0]["unit_price"]) == Decimal("60")
        with pytest.raises(public_catalog.ApplicationError, match="只有待确认"):
            public_catalog.update_tenant_quote_draft_items(session, **kwargs,
                request=PublicQuoteDraftItemsUpdate(items=[{"item_id": quote["item_id"], "unit_price": "90"}]))


@pytest.mark.parametrize("status", ["CONFIRMED", "COMPLETED", "CANCELLED", "EXPIRED", "deleted"])
def test_non_pending_or_deleted_parent_rejects_item_updates(pg_engine, quote, status):
    with Session(pg_engine) as session:
        draft = session.get(PublicQuoteDraftRow, quote["draft_id"])
        if status == "deleted":
            draft.deleted_at = datetime.now(UTC)
        else:
            draft.status = status
        session.commit()
    with tenant_session(pg_engine, quote["tenant_id"]) as session:
        with pytest.raises(DBAPIError, match="only pending"):
            session.execute(text("UPDATE public_quote_draft_items SET unit_price_snapshot=60 WHERE id=:item_id"), quote)
        session.rollback()
        assert session.get(PublicQuoteDraftItemRow, quote["item_id"]).unit_price_snapshot == Decimal("30")


@pytest.mark.parametrize("assignment", [
    "id=gen_random_uuid()", "tenant_id=gen_random_uuid()", "quote_draft_id=gen_random_uuid()",
    "sku_id=gen_random_uuid()", "product_id_snapshot=gen_random_uuid()", "position=2",
    "product_version=2", "sku_version=2", "sku_code_snapshot='OTHER'",
    "minimum_order_quantity=20", "option_values_snapshot=jsonb_build_object('packing_quantity',20)",
    "tags_snapshot='[\"other\"]'::jsonb", "image_url_snapshot='https://example.com/other.png'",
    "customer_note='other'", "created_at=now()", "deleted_at=now()",
])
def test_pending_quote_identity_and_source_are_still_immutable(pg_engine, quote, assignment):
    with tenant_session(pg_engine, quote["tenant_id"]) as session:
        with pytest.raises(DBAPIError, match="identity and source fields are immutable"):
            session.execute(text(f"UPDATE public_quote_draft_items SET {assignment} WHERE id=:item_id"), quote)


def test_pending_currency_edit_and_zero_price_allowed_but_delete_rejected(pg_engine, quote):
    with tenant_session(pg_engine, quote["tenant_id"]) as session:
        session.execute(text("UPDATE public_quote_draft_items SET currency_snapshot='CNY', unit_price_snapshot=0, line_total=0 WHERE id=:item_id"), quote)
        session.commit()
        item = session.get(PublicQuoteDraftItemRow, quote["item_id"])
        assert item.currency_snapshot == "CNY"
        assert item.unit_price_snapshot == Decimal("0")
        with pytest.raises(DBAPIError, match="cannot be deleted"):
            session.execute(text("DELETE FROM public_quote_draft_items WHERE id=:item_id"), quote)


def test_tenant_rls_and_invoker_security_remain_in_force(pg_engine, quote):
    with tenant_session(pg_engine, uuid4()) as session:
        assert session.get(PublicQuoteDraftItemRow, quote["item_id"]) is None
        result = session.execute(text("UPDATE public_quote_draft_items SET unit_price_snapshot=999 WHERE id=:item_id"), quote)
        assert result.rowcount == 0
    with pg_engine.connect() as connection:
        assert connection.scalar(text("SELECT prosecdef FROM pg_proc WHERE oid='public.atc_reject_public_quote_draft_item_mutation()'::regprocedure")) is False
        rows = connection.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid IN ('public_quote_drafts'::regclass, 'public_quote_draft_items'::regclass)"))
        assert all(row.relrowsecurity and row.relforcerowsecurity for row in rows)


def test_concurrent_confirmation_wins_and_pending_edit_rechecks_status(pg_engine, quote):
    # Simulate an editor that reaches the trigger while confirmation holds the
    # parent row. The edit must wait, then reject the now-confirmed parent.
    with tenant_session(pg_engine, quote["tenant_id"]) as confirmer, ThreadPoolExecutor(max_workers=1) as pool:
        confirmer.execute(text("UPDATE public_quote_drafts SET status='CONFIRMED' WHERE id=:draft_id"), quote)

        def attempt_edit():
            with tenant_session(pg_engine, quote["tenant_id"]) as editor:
                editor.execute(text("SET LOCAL statement_timeout='5s'"))
                with pytest.raises(DBAPIError, match="only pending"):
                    editor.execute(text("UPDATE public_quote_draft_items SET unit_price_snapshot=60 WHERE id=:item_id"), quote)

        pending = pool.submit(attempt_edit)
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with pg_engine.connect() as observer:
                    waiting = observer.scalar(text("""
                        SELECT count(*) FROM pg_stat_activity
                        WHERE datname=current_database() AND wait_event_type='Lock'
                          AND query LIKE 'UPDATE public_quote_draft_items SET unit_price_snapshot=60%'
                    """))
                if waiting:
                    break
                time.sleep(0.02)
            assert waiting, "Expected the item trigger to wait on the parent lock"
        finally:
            confirmer.commit()
        pending.result(timeout=6)
