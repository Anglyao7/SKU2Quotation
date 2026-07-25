"""Normalize product categories into a maximum two-level hierarchy.

Revision ID: 20260725_0028
Revises: 20260724_0027
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import context, op


revision = "20260725_0028"
down_revision = "20260724_0027"
branch_labels = None
depends_on = None


def _template_code(path: str) -> str:
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:12].upper()
    return f"TPL-{digest}"


def upgrade() -> None:
    if context.is_offline_mode():
        return
    connection = op.get_bind()
    is_postgresql = connection.dialect.name == "postgresql"
    if is_postgresql:
        op.execute('ALTER TABLE "product_categories" NO FORCE ROW LEVEL SECURITY')

    categories = sa.table(
        "product_categories",
        sa.column("id"),
        sa.column("tenant_id"),
        sa.column("parent_id"),
        sa.column("code"),
        sa.column("name"),
        sa.column("path"),
        sa.column("status"),
        sa.column("sort_order"),
        sa.column("version"),
        sa.column("created_at"),
        sa.column("updated_at"),
        sa.column("deleted_at"),
    )
    rows = list(connection.execute(sa.select(categories)).mappings())
    roots: dict[tuple[object, str], dict[str, object]] = {}
    used_codes: dict[object, set[str]] = {}
    for row in rows:
        used_codes.setdefault(row["tenant_id"], set()).add(str(row["code"]))
        name = str(row["name"]).strip()
        if row["parent_id"] is None and "/" not in name and "／" not in name:
            roots.setdefault(
                (row["tenant_id"], name.casefold()),
                {"id": row["id"], "name": name},
            )

    now = datetime.now(UTC)
    for row in rows:
        if row["parent_id"] is not None:
            continue
        parts = tuple(
            part.strip()
            for part in str(row["name"]).replace("／", "/").split("/")
        )
        if len(parts) != 2 or any(not part for part in parts):
            connection.execute(
                categories.update()
                .where(categories.c.id == row["id"])
                .values(path=str(row["name"]).strip())
            )
            continue
        primary, secondary = parts
        key = (row["tenant_id"], primary.casefold())
        root = roots.get(key)
        if root is None:
            root_id = uuid4()
            root_code = _template_code(primary)
            if root_code in used_codes[row["tenant_id"]]:
                root_code = f"CAT-{root_id.hex[:24].upper()}"
            used_codes[row["tenant_id"]].add(root_code)
            connection.execute(
                categories.insert().values(
                    id=root_id,
                    tenant_id=row["tenant_id"],
                    parent_id=None,
                    code=root_code,
                    name=primary,
                    path=primary,
                    status="ACTIVE",
                    sort_order=0,
                    version=1,
                    created_at=now,
                    updated_at=now,
                    deleted_at=None,
                )
            )
            root = {"id": root_id, "name": primary}
            roots[key] = root
        connection.execute(
            categories.update()
            .where(categories.c.id == row["id"])
            .values(
                parent_id=root["id"],
                name=secondary,
                path=f"{root['name']}/{secondary}",
                version=int(row["version"]) + 1,
                updated_at=now,
            )
        )

    refreshed = list(connection.execute(sa.select(categories)).mappings())
    root_names = {
        row["id"]: str(row["name"]).strip()
        for row in refreshed
        if row["parent_id"] is None
    }
    for row in refreshed:
        if row["parent_id"] is None:
            continue
        parent_name = root_names.get(row["parent_id"])
        if parent_name:
            connection.execute(
                categories.update()
                .where(categories.c.id == row["id"])
                .values(path=f"{parent_name}/{str(row['name']).strip()}")
            )

    if is_postgresql:
        op.execute('ALTER TABLE "product_categories" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    if context.is_offline_mode():
        return
    connection = op.get_bind()
    is_postgresql = connection.dialect.name == "postgresql"
    if is_postgresql:
        op.execute('ALTER TABLE "product_categories" NO FORCE ROW LEVEL SECURITY')
    categories = sa.table(
        "product_categories",
        sa.column("id"),
        sa.column("parent_id"),
        sa.column("name"),
        sa.column("path"),
        sa.column("version"),
    )
    children = list(
        connection.execute(
            sa.select(categories).where(categories.c.parent_id.is_not(None))
        ).mappings()
    )
    for row in children:
        flattened = str(row["path"] or row["name"]).strip()
        connection.execute(
            categories.update()
            .where(categories.c.id == row["id"])
            .values(
                parent_id=None,
                name=flattened,
                path=flattened,
                version=int(row["version"]) + 1,
            )
        )
    if is_postgresql:
        op.execute('ALTER TABLE "product_categories" FORCE ROW LEVEL SECURITY')
