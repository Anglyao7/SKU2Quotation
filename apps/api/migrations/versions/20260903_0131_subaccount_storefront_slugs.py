"""Give customer subaccounts globally unique top-level storefront paths.

Revision ID: 20260903_0131
Revises: 20260903_0130
"""

from __future__ import annotations

import json
import unicodedata

import sqlalchemy as sa
from alembic import op


revision = "20260903_0131"
down_revision = "20260903_0130"
branch_labels = None
depends_on = None

_RESERVED = {
    "account",
    "ai-search",
    "api",
    "assets",
    "console",
    "dashboard",
    "healthz",
    "inquiries",
    "inventory",
    "login",
    "portal",
    "privacy",
    "products",
    "quotations",
    "review",
    "store",
    "suppliers",
    "system",
}


def _slug(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    parts: list[str] = []
    separator_pending = False
    for character in normalized:
        if character.isalnum():
            if separator_pending and parts:
                parts.append("-")
            parts.append(character)
            separator_pending = False
        else:
            separator_pending = bool(parts)
    result = "".join(parts).strip("-")[:80].rstrip("-") or "account"
    if result in _RESERVED:
        suffix = "-store"
        result = f"{result[: 80 - len(suffix)].rstrip('-')}{suffix}"
    return result


def _unique(base: str, occupied: set[str]) -> str:
    if base not in occupied:
        return base
    counter = 2
    while True:
        suffix = f"-{counter}"
        candidate = f"{base[: 80 - len(suffix)].rstrip('-')}{suffix}"
        if candidate not in occupied:
            return candidate
        counter += 1


def _legacy_slugs(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def upgrade() -> None:
    bind = op.get_bind()
    offline = op.get_context().as_sql
    if offline:
        op.add_column(
            "memberships",
            sa.Column("storefront_slug", sa.String(length=80), nullable=True),
        )
        op.create_index(
            "uq_memberships_storefront_slug",
            "memberships",
            ["storefront_slug"],
            unique=True,
        )
        return

    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("memberships")}
    if "storefront_slug" not in columns:
        with op.batch_alter_table("memberships") as batch:
            batch.add_column(
                sa.Column("storefront_slug", sa.String(length=80), nullable=True)
            )

    occupied = {
        str(value).casefold().strip()
        for value in bind.execute(sa.text("SELECT slug FROM tenants")).scalars()
        if str(value or "").strip()
    }
    for profile_slug, legacy in bind.execute(
        sa.text("SELECT slug, legacy_slugs FROM tenant_public_profiles")
    ).all():
        occupied.update(
            str(value).casefold().strip()
            for value in [profile_slug, *_legacy_slugs(legacy)]
            if str(value or "").strip()
        )

    rows = bind.execute(
        sa.text(
            "SELECT memberships.id, memberships.login_identifier, "
            "users.email_normalized, users.display_name "
            "FROM memberships JOIN users ON users.id = memberships.user_id "
            "WHERE memberships.account_scope = 'CUSTOMER_SUBACCOUNT' "
            "AND memberships.status <> 'removed' "
            "AND memberships.deleted_at IS NULL"
        )
    ).all()
    for membership_id, login_identifier, email, display_name in rows:
        source = str(login_identifier or email or display_name or "account").strip()
        if "@" in source:
            source = source.split("@", 1)[0]
        base = _slug(source or display_name or "account")
        storefront_slug = _unique(base, occupied)
        occupied.add(storefront_slug)
        bind.execute(
            sa.text(
                "UPDATE memberships SET storefront_slug = :storefront_slug "
                "WHERE id = :membership_id"
            ),
            {
                "storefront_slug": storefront_slug,
                "membership_id": membership_id,
            },
        )

    index_names = {item["name"] for item in sa.inspect(bind).get_indexes("memberships")}
    if "uq_memberships_storefront_slug" not in index_names:
        op.create_index(
            "uq_memberships_storefront_slug",
            "memberships",
            ["storefront_slug"],
            unique=True,
        )


def downgrade() -> None:
    if op.get_context().as_sql:
        op.drop_index("uq_memberships_storefront_slug", table_name="memberships")
        op.drop_column("memberships", "storefront_slug")
        return
    columns = {
        item["name"] for item in sa.inspect(op.get_bind()).get_columns("memberships")
    }
    if "storefront_slug" not in columns:
        return
    indexes = {
        item["name"] for item in sa.inspect(op.get_bind()).get_indexes("memberships")
    }
    if "uq_memberships_storefront_slug" in indexes:
        op.drop_index("uq_memberships_storefront_slug", table_name="memberships")
    with op.batch_alter_table("memberships") as batch:
        batch.drop_column("storefront_slug")
