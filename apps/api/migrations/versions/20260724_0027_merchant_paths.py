"""Use merchant names as storefront paths and preserve old links.

Revision ID: 20260724_0027
Revises: 20260724_0026
"""

from __future__ import annotations

import unicodedata

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql


revision = "20260724_0027"
down_revision = "20260724_0026"
branch_labels = None
depends_on = None


JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
RESERVED = {
    "account",
    "ai-search",
    "api",
    "assets",
    "console",
    "dashboard",
    "healthz",
    "inquiries",
    "login",
    "privacy",
    "products",
    "quotations",
    "review",
    "store",
    "suppliers",
    "system",
}


def _slug_from_name(value: str, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    parts: list[str] = []
    pending_separator = False
    for character in normalized:
        if character.isalnum():
            if pending_separator and parts:
                parts.append("-")
            parts.append(character)
            pending_separator = False
        else:
            pending_separator = bool(parts)
    slug = "".join(parts).strip("-")[:80].rstrip("-") or fallback
    if slug in RESERVED:
        suffix = "-store"
        slug = f"{slug[: 80 - len(suffix)].rstrip('-')}{suffix}"
    return slug


def _unique_slug(base: str, tenant_id: object, used: set[str]) -> str:
    if base not in used:
        return base
    suffix = f"-{str(tenant_id).replace('-', '')[:8]}"
    candidate = f"{base[: 80 - len(suffix)].rstrip('-')}{suffix}"
    counter = 2
    while candidate in used:
        numbered = f"-{counter}"
        candidate = f"{base[: 80 - len(numbered)].rstrip('-')}{numbered}"
        counter += 1
    return candidate


def upgrade() -> None:
    op.add_column(
        "tenant_public_profiles",
        sa.Column(
            "legacy_slugs",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    if context.is_offline_mode():
        # Existing merchant names are backfilled by the online migration path,
        # where rows can be normalized and collision-checked deterministically.
        return

    connection = op.get_bind()
    is_postgresql = connection.dialect.name == "postgresql"
    if is_postgresql:
        op.execute('ALTER TABLE "tenants" NO FORCE ROW LEVEL SECURITY')
        op.execute(
            'ALTER TABLE "tenant_public_profiles" NO FORCE ROW LEVEL SECURITY'
        )

    tenants = sa.table(
        "tenants",
        sa.column("id"),
        sa.column("name"),
        sa.column("slug"),
    )
    profiles = sa.table(
        "tenant_public_profiles",
        sa.column("tenant_id"),
        sa.column("slug"),
        sa.column("legacy_slugs", JSON_DOCUMENT),
    )
    rows = list(
        connection.execute(
            sa.select(
                tenants.c.id,
                tenants.c.name,
                tenants.c.slug.label("tenant_slug"),
                profiles.c.slug.label("profile_slug"),
            ).select_from(
                tenants.outerjoin(
                    profiles,
                    profiles.c.tenant_id == tenants.c.id,
                )
            )
        ).mappings()
    )

    used: set[str] = set()
    destinations: dict[object, str] = {}
    for row in sorted(rows, key=lambda item: str(item["id"])):
        base = _slug_from_name(str(row["name"]), str(row["tenant_slug"]))
        destination = _unique_slug(base, row["id"], used)
        destinations[row["id"]] = destination
        used.add(destination)

    for row in rows:
        temporary = f"__migration__{str(row['id']).replace('-', '')}"
        connection.execute(
            tenants.update()
            .where(tenants.c.id == row["id"])
            .values(slug=temporary)
        )
        if row["profile_slug"] is not None:
            connection.execute(
                profiles.update()
                .where(profiles.c.tenant_id == row["id"])
                .values(slug=temporary)
            )

    canonical_slugs = set(destinations.values())
    for row in rows:
        destination = destinations[row["id"]]
        aliases: list[str] = []
        for alias in (row["tenant_slug"], row["profile_slug"]):
            normalized = str(alias or "").casefold().strip()
            if (
                normalized
                and normalized != destination
                and normalized not in canonical_slugs
                and normalized not in aliases
            ):
                aliases.append(normalized)
        connection.execute(
            tenants.update()
            .where(tenants.c.id == row["id"])
            .values(slug=destination)
        )
        if row["profile_slug"] is not None:
            connection.execute(
                profiles.update()
                .where(profiles.c.tenant_id == row["id"])
                .values(slug=destination, legacy_slugs=aliases)
            )

    if is_postgresql:
        op.execute('ALTER TABLE "tenant_public_profiles" FORCE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "tenants" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_column("tenant_public_profiles", "legacy_slugs")
