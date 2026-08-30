"""Prune storefront languages that do not have a published package.

Revision ID: 20260830_0125
Revises: 20260830_0124
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260830_0125"
down_revision = "20260830_0124"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)

SUPPORTED_LOCALES = (
    "zh-CN",
    "en-US",
    "es",
    "tr",
    "ar",
    "ja",
    "ko",
    "pt",
)

_TENANT_RLS_TABLES = (
    "tenants",
    "tenant_public_profiles",
    "catalog_language_packs",
)


def _temporarily_unforce_tenant_rls(bind: sa.Connection) -> tuple[str, ...]:
    """Let the migration owner reconcile every tenant in one transaction."""

    if bind.dialect.name != "postgresql":
        return ()
    forced_tables: list[str] = []
    for table_name in _TENANT_RLS_TABLES:
        forced = bind.scalar(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class "
                "WHERE oid = to_regclass(:table_name)"
            ),
            {"table_name": f'public."{table_name}"'},
        )
        if forced:
            op.execute(f'ALTER TABLE public."{table_name}" NO FORCE ROW LEVEL SECURITY')
            forced_tables.append(table_name)
    return tuple(forced_tables)


def _restore_forced_tenant_rls(table_names: tuple[str, ...]) -> None:
    for table_name in table_names:
        op.execute(f'ALTER TABLE public."{table_name}" FORCE ROW LEVEL SECURITY')


def _normalize_locale(value: object) -> str | None:
    normalized = str(value or "").strip().replace("_", "-").casefold()
    aliases = {
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "en": "en-US",
        "en-us": "en-US",
        "es": "es",
        "es-es": "es",
        "tr": "tr",
        "tr-tr": "tr",
        "ar": "ar",
        "ar-sa": "ar",
        "ja": "ja",
        "ja-jp": "ja",
        "ko": "ko",
        "ko-kr": "ko",
        "pt": "pt",
        "pt-br": "pt",
        "pt-pt": "pt",
    }
    return aliases.get(normalized)


def upgrade() -> None:
    if op.get_context().as_sql:
        return
    bind = op.get_bind()
    forced_tables = _temporarily_unforce_tenant_rls(bind)
    profiles = sa.table(
        "tenant_public_profiles",
        sa.column("tenant_id", sa.Uuid(as_uuid=True)),
        sa.column("storefront_locales", JSON_DOCUMENT),
        sa.column("storefront_default_locale", sa.String(20)),
    )
    tenants = sa.table(
        "tenants",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("default_locale", sa.String(20)),
    )
    packs = sa.table(
        "catalog_language_packs",
        sa.column("tenant_id", sa.Uuid(as_uuid=True)),
        sa.column("target_locale", sa.String(20)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    rows = list(
        bind.execute(
            sa.select(
                profiles.c.tenant_id,
                profiles.c.storefront_locales,
                profiles.c.storefront_default_locale,
                tenants.c.default_locale,
            ).select_from(
                profiles.join(tenants, tenants.c.id == profiles.c.tenant_id)
            )
        ).mappings()
    )
    for row in rows:
        tenant_id = row["tenant_id"]
        source_locale = _normalize_locale(row["default_locale"]) or "zh-CN"
        configured = {
            locale
            for value in bind.execute(
                sa.select(packs.c.target_locale).where(
                    packs.c.tenant_id == tenant_id,
                    packs.c.deleted_at.is_(None),
                )
            ).scalars()
            if (locale := _normalize_locale(value)) is not None
        }
        configured.add(source_locale)
        selected_values = (
            row["storefront_locales"]
            if isinstance(row["storefront_locales"], list)
            else []
        )
        selected = {
            locale
            for value in selected_values
            if (locale := _normalize_locale(value)) is not None
        }
        selected.add(source_locale)
        active = [source_locale]
        active.extend(
            locale
            for locale in SUPPORTED_LOCALES
            if locale != source_locale
            and locale in selected
            and locale in configured
        )
        requested_default = _normalize_locale(row["storefront_default_locale"])
        default_locale = (
            requested_default if requested_default in active else source_locale
        )
        bind.execute(
            profiles.update()
            .where(profiles.c.tenant_id == tenant_id)
            .values(
                storefront_locales=active,
                storefront_default_locale=default_locale,
            )
        )
    _restore_forced_tenant_rls(forced_tables)


def downgrade() -> None:
    # Removed selections cannot be reconstructed safely; no schema is changed.
    return
