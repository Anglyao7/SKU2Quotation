"""Backfill child storefront paths missed by the FORCE-RLS migration owner.

Revision ID: 20260906_0133
Revises: 20260903_0132
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "20260906_0133"
down_revision = "20260903_0132"
branch_labels = None
depends_on = None

_TABLES = ("memberships", "tenant_public_profiles", "tenants", "users")


def _original_slug_rules():
    # Freeze the same rules used by the original migration, not mutable app
    # helpers. This repair must preserve existing, nonempty public addresses.
    path = Path(__file__).with_name("20260903_0131_subaccount_storefront_slugs.py")
    spec = importlib.util.spec_from_file_location("storefront_slug_migration_0131", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def backfill_missing_paths(bind) -> int:
    rules = _original_slug_rules()
    occupied = {
        str(slug).casefold().strip()
        for slug in bind.execute(sa.text("SELECT slug FROM tenants")).scalars()
        if str(slug or "").strip()
    }
    for slug, legacy in bind.execute(
        sa.text("SELECT slug, legacy_slugs FROM tenant_public_profiles")
    ):
        occupied.update(
            str(value).casefold().strip()
            for value in [slug, *rules._legacy_slugs(legacy)]
            if str(value or "").strip()
        )
    occupied.update(
        str(slug).casefold().strip()
        for slug in bind.execute(
            sa.text("SELECT storefront_slug FROM memberships")
        ).scalars()
        if str(slug or "").strip()
    )
    rows = bind.execute(sa.text(
        "SELECT m.id, m.login_identifier, u.email_normalized, u.display_name "
        "FROM memberships m JOIN users u ON u.id = m.user_id "
        "WHERE m.account_scope = 'CUSTOMER_SUBACCOUNT' "
        "AND m.status <> 'removed' AND m.deleted_at IS NULL "
        "AND (m.storefront_slug IS NULL OR trim(m.storefront_slug) = '') "
        "ORDER BY m.created_at, m.id"
    )).all()
    for membership_id, login, email, display_name in rows:
        source = str(login or email or display_name or "account").strip()
        if "@" in source:
            source = source.split("@", 1)[0]
        slug = rules._unique(rules._slug(source or display_name or "account"), occupied)
        occupied.add(slug)
        bind.execute(sa.text(
            "UPDATE memberships SET storefront_slug = :slug WHERE id = :id "
            "AND (storefront_slug IS NULL OR trim(storefront_slug) = '')"
        ), {"slug": slug, "id": membership_id})
    return len(rows)


def upgrade() -> None:
    if op.get_context().as_sql:
        # Like 0131's identity backfill, this data-dependent repair runs online.
        return
    bind = op.get_bind()
    forced_tables: list[str] = []
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SELECT pg_advisory_xact_lock(487221302517390)"))
        forced_tables = [
            name for name in _TABLES
            if bind.execute(sa.text(
                "SELECT relforcerowsecurity FROM pg_class "
                "WHERE oid = to_regclass(:table_name)"
            ), {"table_name": f"public.{name}"}).scalar_one()
        ]
        # Only the table owner is exempted, inside this migration transaction.
        # Runtime roles keep their tenant RLS policies; no data grants change.
        for name in forced_tables:
            op.execute(f'ALTER TABLE public."{name}" NO FORCE ROW LEVEL SECURITY')
    try:
        backfill_missing_paths(bind)
    finally:
        for name in forced_tables:
            op.execute(f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    # Public addresses are durable business identifiers. Do not erase them
    # when rolling application code back to the previous schema-compatible release.
    pass
