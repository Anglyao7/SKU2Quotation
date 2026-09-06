from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app import db_models  # noqa: F401 -- register import/job relationships
from app.model_mixins import utcnow
from app.product_supplier_models import ProductRow
from app.repositories.public_catalog_repository import _public_catalog_statement


@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()])
def test_category_memberships_are_resolved_without_per_sku_subqueries(dialect):
    tenant_id = uuid4()
    statement = _public_catalog_statement(
        tenant_id=tenant_id, now=utcnow(), query="", category="Root/Child",
    ).with_only_columns(ProductRow.id)
    sql = str(statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))

    assert "products.category_id IN (SELECT product_categories.id" in sql
    assert "products.id IN (SELECT product_category_memberships.product_id" in sql
    assert "product_category_memberships.product_id = products.id" not in sql
    assert "additional_product_category.status = 'ACTIVE'" in sql
    assert "additional_product_category.deleted_at IS NULL" in sql
    assert "product_category_memberships.tenant_id =" in sql


def test_lexical_search_uses_the_same_bounded_membership_lookup():
    statement = _public_catalog_statement(
        tenant_id=uuid4(), now=utcnow(), query="child", category=None,
    ).with_only_columns(ProductRow.id)
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "products.id IN (SELECT product_category_memberships.product_id" in sql
    assert "product_category_memberships.product_id = products.id" not in sql
