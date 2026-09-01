from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..catalog_translation_models import (
    CatalogLanguagePackRow,
    CatalogSkuTranslationRow,
    CatalogTranslationOverrideRow,
)
from ..services.catalog_translation import (
    CatalogTranslationResult,
    CatalogTranslationSource,
)


def translation_map(
    session: Session,
    *,
    tenant_id: UUID,
    sku_ids: list[UUID],
    target_locale: str,
) -> dict[UUID, CatalogSkuTranslationRow]:
    if not sku_ids:
        return {}
    rows = session.scalars(
        select(CatalogSkuTranslationRow).where(
            CatalogSkuTranslationRow.tenant_id == tenant_id,
            CatalogSkuTranslationRow.sku_id.in_(sku_ids),
            CatalogSkuTranslationRow.target_locale == target_locale,
        )
    ).all()
    return {row.sku_id: row for row in rows}


def category_translation_map(
    session: Session,
    *,
    tenant_id: UUID,
    target_locale: str,
) -> dict[str, str]:
    rows = session.execute(
        select(
            CatalogSkuTranslationRow.source_category,
            func.max(CatalogSkuTranslationRow.category),
        )
        .where(
            CatalogSkuTranslationRow.tenant_id == tenant_id,
            CatalogSkuTranslationRow.target_locale == target_locale,
            CatalogSkuTranslationRow.source_category.is_not(None),
            CatalogSkuTranslationRow.category.is_not(None),
        )
        .group_by(CatalogSkuTranslationRow.source_category)
    ).all()
    result: dict[str, str] = {}
    for source_category, translated_category in rows:
        source = str(source_category or "").strip()
        translated = str(translated_category or "").strip()
        if source and translated:
            result.setdefault(source, translated)
    return result


def available_target_locales(
    session: Session,
    *,
    tenant_id: UUID,
) -> list[str]:
    return list(
        session.scalars(
            select(CatalogSkuTranslationRow.target_locale)
            .where(CatalogSkuTranslationRow.tenant_id == tenant_id)
            .distinct()
            .order_by(CatalogSkuTranslationRow.target_locale)
        ).all()
    )


def count_translations(
    session: Session,
    *,
    tenant_id: UUID,
    target_locale: str,
) -> int:
    return int(
        session.scalar(
            select(func.count(CatalogSkuTranslationRow.id)).where(
                CatalogSkuTranslationRow.tenant_id == tenant_id,
                CatalogSkuTranslationRow.target_locale == target_locale,
            )
        )
        or 0
    )


def latest_translation_updated_at(
    session: Session,
    *,
    tenant_id: UUID,
    target_locale: str,
) -> datetime | None:
    return session.scalar(
        select(func.max(CatalogSkuTranslationRow.updated_at)).where(
            CatalogSkuTranslationRow.tenant_id == tenant_id,
            CatalogSkuTranslationRow.target_locale == target_locale,
        )
    )


def latest_translation_override_updated_at(
    session: Session,
    *,
    tenant_id: UUID,
    target_locale: str,
) -> datetime | None:
    return session.scalar(
        select(func.max(CatalogTranslationOverrideRow.updated_at)).where(
            CatalogTranslationOverrideRow.tenant_id == tenant_id,
            CatalogTranslationOverrideRow.target_locale == target_locale,
        )
    )


def language_pack(
    session: Session,
    *,
    tenant_id: UUID,
    target_locale: str,
) -> CatalogLanguagePackRow | None:
    return session.scalar(
        select(CatalogLanguagePackRow).where(
            CatalogLanguagePackRow.tenant_id == tenant_id,
            CatalogLanguagePackRow.target_locale == target_locale,
            CatalogLanguagePackRow.deleted_at.is_(None),
        )
    )


def available_language_pack_locales(
    session: Session,
    *,
    tenant_id: UUID,
) -> list[str]:
    return list(
        session.scalars(
            select(CatalogLanguagePackRow.target_locale)
            .where(
                CatalogLanguagePackRow.tenant_id == tenant_id,
                CatalogLanguagePackRow.deleted_at.is_(None),
            )
            .order_by(CatalogLanguagePackRow.target_locale)
        ).all()
    )


def translation_override_map(
    session: Session,
    *,
    tenant_id: UUID,
    target_locale: str,
    entity_types: tuple[str, ...] = ("PRODUCT", "SKU"),
    entity_ids: set[UUID] | None = None,
) -> dict[tuple[str, UUID], CatalogTranslationOverrideRow]:
    statement = select(CatalogTranslationOverrideRow).where(
        CatalogTranslationOverrideRow.tenant_id == tenant_id,
        CatalogTranslationOverrideRow.target_locale == target_locale,
        CatalogTranslationOverrideRow.entity_type.in_(entity_types),
    )
    if entity_ids is not None:
        if not entity_ids:
            return {}
        statement = statement.where(
            CatalogTranslationOverrideRow.entity_id.in_(entity_ids)
        )
    rows = session.scalars(statement).all()
    return {(row.entity_type, row.entity_id): row for row in rows}


def save_translation_override(
    session: Session,
    *,
    tenant_id: UUID,
    target_locale: str,
    entity_type: str,
    entity_id: UUID,
    source_hash: str,
    values: dict[str, object],
    updated_by_user_id: UUID,
) -> CatalogTranslationOverrideRow:
    row = session.scalar(
        select(CatalogTranslationOverrideRow).where(
            CatalogTranslationOverrideRow.tenant_id == tenant_id,
            CatalogTranslationOverrideRow.target_locale == target_locale,
            CatalogTranslationOverrideRow.entity_type == entity_type,
            CatalogTranslationOverrideRow.entity_id == entity_id,
        )
    )
    if row is None:
        row = CatalogTranslationOverrideRow(
            tenant_id=tenant_id,
            target_locale=target_locale,
            entity_type=entity_type,
            entity_id=entity_id,
            source_hash=source_hash,
            values=dict(values),
            updated_by_user_id=updated_by_user_id,
        )
        session.add(row)
        return row
    row.source_hash = source_hash
    row.values = dict(values)
    row.updated_by_user_id = updated_by_user_id
    return row


def save_language_pack(
    session: Session,
    *,
    tenant_id: UUID,
    source_locale: str,
    target_locale: str,
    version: int,
    object_key: str,
    public_url: str | None,
    content_sha256: str,
    source_digest: str,
    storage_fingerprint: str,
    byte_size: int,
    product_count: int,
    sku_count: int,
    category_count: int,
    provider: str,
    provider_version: str,
    source_cutoff_at: datetime,
    published_at: datetime,
    full_rebuild: bool,
) -> CatalogLanguagePackRow:
    row = language_pack(
        session,
        tenant_id=tenant_id,
        target_locale=target_locale,
    )
    if row is None:
        row = CatalogLanguagePackRow(
            tenant_id=tenant_id,
            source_locale=source_locale,
            target_locale=target_locale,
            version=version,
            object_key=object_key,
            public_url=public_url,
            content_sha256=content_sha256,
            source_digest=source_digest,
            storage_fingerprint=storage_fingerprint,
            content_encoding="gzip",
            byte_size=byte_size,
            product_count=product_count,
            sku_count=sku_count,
            category_count=category_count,
            provider=provider,
            provider_version=provider_version,
            source_cutoff_at=source_cutoff_at,
            published_at=published_at,
            last_full_translation_at=published_at if full_rebuild else None,
        )
        session.add(row)
        return row

    row.source_locale = source_locale
    row.version = version
    row.object_key = object_key
    row.public_url = public_url
    row.content_sha256 = content_sha256
    row.source_digest = source_digest
    row.storage_fingerprint = storage_fingerprint
    row.content_encoding = "gzip"
    row.byte_size = byte_size
    row.product_count = product_count
    row.sku_count = sku_count
    row.category_count = category_count
    row.provider = provider
    row.provider_version = provider_version
    row.source_cutoff_at = source_cutoff_at
    row.published_at = published_at
    if full_rebuild:
        row.last_full_translation_at = published_at
    return row


def save_translation(
    session: Session,
    *,
    tenant_id: UUID,
    source_locale: str,
    target_locale: str,
    source: CatalogTranslationSource,
    result: CatalogTranslationResult,
    provider: str,
    provider_version: str,
) -> CatalogSkuTranslationRow:
    row = session.scalar(
        select(CatalogSkuTranslationRow).where(
            CatalogSkuTranslationRow.tenant_id == tenant_id,
            CatalogSkuTranslationRow.sku_id == source.sku_id,
            CatalogSkuTranslationRow.target_locale == target_locale,
        )
    )
    if row is None:
        row = CatalogSkuTranslationRow(
            tenant_id=tenant_id,
            sku_id=source.sku_id,
            source_locale=source_locale,
            target_locale=target_locale,
            source_hash=source.source_hash,
            source_category=source.category,
            name=result.name,
            description=result.description,
            category=result.category,
            tags=list(result.tags),
            display_tag=result.display_tag,
            provider=provider,
            provider_version=provider_version,
            product_version=source.product_version,
            sku_version=source.sku_version,
        )
        session.add(row)
        return row

    row.source_locale = source_locale
    row.source_hash = source.source_hash
    row.source_category = source.category
    row.name = result.name
    row.description = result.description
    row.category = result.category
    row.tags = list(result.tags)
    row.display_tag = result.display_tag
    row.provider = provider
    row.provider_version = provider_version
    row.product_version = source.product_version
    row.sku_version = source.sku_version
    return row
