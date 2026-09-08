"""Real PostgreSQL migration/constraint/RLS regression using a disposable database."""
import importlib
import os
from uuid import UUID, uuid4
from datetime import datetime, UTC

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, MetaData, Table, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.types import NullType
from sqlalchemy.exc import DBAPIError


def migrate(connection, revision, direction="upgrade"):
    module = importlib.import_module(f"migrations.versions.{revision}")
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


@pytest.fixture
def pg():
    url = os.getenv("ATC_STOREFRONT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("isolated PostgreSQL storefront URL not configured")
    engine = create_engine(url)
    assert engine.url.database.startswith("atc_storefront_test_")
    with engine.begin() as connection:
        assert not connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).all(), "Use a fresh disposable database"
        connection.execute(text("CREATE TABLE tenants (id uuid PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE users (id uuid PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE memberships (id uuid PRIMARY KEY, tenant_id uuid REFERENCES tenants(id), UNIQUE(tenant_id,id))"))
        connection.execute(text("CREATE TABLE tenant_public_profiles (tenant_id uuid PRIMARY KEY REFERENCES tenants(id))"))
        migrate(connection, "20260830_0121_storefront_custom_pages")
        migrate(connection, "20260830_0122_route_exchange_rate_visibility")
        migrate(connection, "20260908_0136_subaccount_storefront_settings")
        # Empty schemas can roll back and re-upgrade without losing parent pages.
        migrate(connection, "20260908_0136_subaccount_storefront_settings", "downgrade")
        migrate(connection, "20260908_0136_subaccount_storefront_settings")
        migrate(connection, "20260908_0137_storefront_sorting_rules")
        migrate(connection, "20260908_0137_storefront_sorting_rules", "downgrade")
        migrate(connection, "20260908_0137_storefront_sorting_rules")
    yield engine
    engine.dispose()


def test_postgres_account_page_namespace_and_profile_rls(pg):
    tenant, other_tenant, first, second, outsider = [str(uuid4()) for _ in range(5)]
    role = "atc_storefront_test_" + uuid4().hex[:10]
    with pg.begin() as connection:
        connection.execute(text("INSERT INTO tenants VALUES (:first), (:second)"), {"first": tenant, "second": other_tenant})
        for member, owner in ((first, tenant), (second, tenant), (outsider, other_tenant)):
            connection.execute(text("INSERT INTO memberships VALUES (:id, :tenant)"), {"id": member, "tenant": owner})
        connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
        connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        connection.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'))

    def page(connection, owner):
        connection.execute(text("""INSERT INTO storefront_custom_pages
            (id,tenant_id,owner_membership_id,title,slug,object_key,original_filename,content_sha256,byte_size,created_at,updated_at)
            VALUES (:id,:tenant,:owner,'Own page','about','test.html','test.html',:digest,1,now(),now())"""),
            {"id": str(uuid4()), "tenant": tenant, "owner": owner, "digest": "a" * 64})

    try:
        with pg.begin() as connection:
            for owner in (None, first, second):
                page(connection, owner)
            connection.execute(text("INSERT INTO subaccount_storefront_profiles (tenant_id,membership_id,settings,created_at,updated_at) VALUES (:tenant,:member,'{}',now(),now())"), {"tenant": tenant, "member": first})
            connection.execute(text("INSERT INTO subaccount_storefront_profiles (tenant_id,membership_id,settings,created_at,updated_at) VALUES (:tenant,:member,'{}',now(),now())"), {"tenant": other_tenant, "member": outsider})
        for owner in (None, first, second, outsider):
            with pytest.raises(DBAPIError):
                with pg.begin() as connection:
                    page(connection, owner)  # duplicate scope, or cross-tenant FK
        with pg.begin() as connection:
            connection.execute(text(f'SET LOCAL ROLE "{role}"'))
            connection.execute(text("SELECT set_config('app.current_tenant_id', :tenant, true)"), {"tenant": tenant})
            rows = connection.execute(text("SELECT membership_id FROM subaccount_storefront_profiles")).scalars().all()
            assert [str(value) for value in rows] == [first]
            assert connection.execute(text("UPDATE subaccount_storefront_profiles SET settings=CAST(:settings AS jsonb) WHERE membership_id=:id"), {"id": first, "settings": '{"hot_products_enabled":true}'}).rowcount == 1
            assert connection.execute(text("UPDATE subaccount_storefront_profiles SET settings='{}' WHERE membership_id=:id"), {"id": outsider}).rowcount == 0
        with pytest.raises(DBAPIError):
            with pg.begin() as connection:
                connection.execute(text(f'SET LOCAL ROLE "{role}"'))
                connection.execute(text("SELECT set_config('app.current_tenant_id', :tenant, true)"), {"tenant": other_tenant})
                connection.execute(text("INSERT INTO subaccount_storefront_profiles (tenant_id,membership_id,settings,created_at,updated_at) VALUES (:tenant,:member,'{}',now(),now())"), {"tenant": tenant, "member": second})
        with pytest.raises(RuntimeError, match="Export account storefront"):
            with pg.begin() as connection:
                migrate(connection, "20260908_0136_subaccount_storefront_settings", "downgrade")
        _assert_postgres_sorting_queries(pg, UUID(tenant))
    finally:
        with pg.begin() as connection:
            connection.execute(text(f'DROP OWNED BY "{role}"'))
            connection.execute(text(f'DROP ROLE "{role}"'))


def _assert_postgres_sorting_queries(engine, tenant_id):
    """Execute real grouped SQL, including bound CASE and category subqueries.

    The miniature catalog omits unrelated foreign keys; migration constraints
    and RLS are tested above against the actual migrations.
    """
    from app.repositories import public_catalog_repository as catalog
    from app.product_supplier_models import ProductRow, ProductCategoryRow, ProductCategoryMembershipRow
    from app.product_center_models import SkuRow
    from app.public_catalog_models import PublicCatalogOfferRow, PublicQuoteDraftRow, PublicQuoteDraftItemRow
    from app.storefront_analytics_models import StorefrontProductViewDailyRow

    metadata = MetaData()
    for model in (ProductRow, ProductCategoryRow, ProductCategoryMembershipRow, SkuRow, PublicCatalogOfferRow, PublicQuoteDraftRow, PublicQuoteDraftItemRow, StorefrontProductViewDailyRow):
        Table(model.__tablename__, metadata, *[Column(col.name, col.type, primary_key=col.primary_key, nullable=True) for col in model.__table__.columns if not isinstance(col.type, NullType)])
    metadata.create_all(engine)
    product_id, category_id, sku_id = uuid4(), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(metadata.tables["product_categories"].insert().values(id=category_id, tenant_id=tenant_id, name="Priority", code="PRIORITY", status="ACTIVE", sort_order=0))
        connection.execute(metadata.tables["products"].insert().values(id=product_id, tenant_id=tenant_id, category_id=category_id, name="Popular product", status="ACTIVE"))
        connection.execute(metadata.tables["skus"].insert().values(id=sku_id, tenant_id=tenant_id, product_id=product_id, name="One", sku_code="TEST", status="ACTIVE"))
        connection.execute(metadata.tables["public_catalog_offers"].insert().values(id=uuid4(), tenant_id=tenant_id, sku_id=sku_id, publication_status="PUBLISHED", currency="CNY", unit_price=10, tags=[]))
        connection.execute(metadata.tables["storefront_product_view_daily"].insert().values(id=uuid4(), tenant_id=tenant_id, product_id=product_id, viewed_on=datetime.now(UTC).date(), view_count=5))
    with Session(engine) as session:
        for priority in (None, [], [product_id]):
            result = catalog.list_public_product_ids_page(session, tenant_id=tenant_id, now=datetime.now(UTC), query="", category=None, tags=set(), page=1, page_size=20, priority_product_order=priority, priority_category_ids=[category_id])
            assert result == [product_id]
        assert catalog.hot_product_candidates(session, tenant_id=tenant_id, now=datetime.now(UTC), excluded_product_ids=set(), limit=20) == [product_id]
        assert catalog.hot_product_candidates(session, tenant_id=tenant_id, now=datetime.now(UTC), excluded_product_ids={product_id}, limit=20) == []
