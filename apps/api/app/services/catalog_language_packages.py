"""Build immutable, browser-consumable storefront catalog language packs."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from ..catalog_translation_models import (
    CatalogLanguagePackRow,
    CatalogSkuTranslationRow,
)
from ..model_mixins import utcnow
from .catalog_translation import (
    catalog_translation_source,
)
from .language_package_storage import LanguagePackageStorage
from .translation import TranslationProvider, TranslationProviderError
from .translation_memory import translate_values_with_memory


logger = logging.getLogger(__name__)
PACKAGE_SCHEMA = "atc-catalog-language-pack"
PACKAGE_SCHEMA_VERSION = 2
_CJK_TEXT = re.compile(r"[\u3400-\u9fff]")
_LATIN_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ\u0100-\u024F]{2,}")
_OPTION_INTERNAL_KEY = "_sku2quotation"
_OPTION_METADATA_KEYS = frozenset(
    {
        _OPTION_INTERNAL_KEY,
        "商品编码",
        "商品型号",
        "规格名称",
        "备注",
        "一箱个数",
        "装箱数",
        "毛重",
        "起定数",
        "是否是新品",
    }
)


@dataclass(frozen=True, slots=True)
class CatalogLanguagePackBuild:
    payload: dict[str, Any]
    compressed: bytes
    content_sha256: str
    source_digest: str
    source_cutoff_at: datetime
    product_count: int
    sku_count: int
    category_count: int


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _catalog_sources_digest(
    product_sources: list[dict[str, Any]],
    sku_sources: list[dict[str, Any]],
) -> str:
    return _json_hash(
        {
            "package_schema_version": PACKAGE_SCHEMA_VERSION,
            "products": sorted(
                (
                    source["product_id"],
                    source["source_hash"],
                )
                for source in product_sources
            ),
            "skus": sorted(
                (
                    source["sku_id"],
                    source["source_hash"],
                )
                for source in sku_sources
            ),
        }
    )


def catalog_rows_source_digest(rows: list[object]) -> str:
    """Fingerprint every field included in a storefront language package."""

    return _catalog_sources_digest(
        [_product_source(group) for group in _group_rows(rows)],
        [_sku_source(row) for row in rows],
    )


def _category_path(category: object | None) -> str | None:
    if category is None:
        return None
    path = str(getattr(category, "path", "") or "").strip()
    name = str(getattr(category, "name", "") or "").strip()
    code = str(getattr(category, "code", "") or "").strip()
    if path and code and path.casefold() == code.casefold():
        return name or None
    return path or name or None


def _clean_tags(rows: list[object]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(tag).strip()
            for row in rows
            for tag in (row[0].tags or [])
            if str(tag).strip()
        )
    )


def _display_tag(rows: list[object], tags: tuple[str, ...]) -> str | None:
    lookup = {tag.casefold(): tag for tag in tags}
    for row in rows:
        requested = str(row[0].display_tag or "").strip()
        if requested and requested.casefold() in lookup:
            return lookup[requested.casefold()]
    return tags[0] if tags else None


def _option_text(value: object) -> str | None:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (str, int, float, Decimal)):
        normalized = str(value).strip()
        return normalized or None
    return None


def _variant_option_keys(rows: list[object]) -> tuple[str, ...]:
    explicit: list[str] = []
    for row in rows:
        option_values = row[1].option_values or {}
        marker = option_values.get(_OPTION_INTERNAL_KEY)
        marker_keys = marker.get("variant_option_keys", []) if isinstance(marker, dict) else []
        for key in marker_keys:
            normalized = str(key).strip() if isinstance(key, str) else ""
            if normalized and normalized not in explicit:
                explicit.append(normalized)
    if explicit:
        return tuple(explicit)

    discovered: list[str] = []
    for row in rows:
        for key, value in (row[1].option_values or {}).items():
            normalized = str(key).strip()
            if (
                normalized
                and normalized not in _OPTION_METADATA_KEYS
                and not normalized.startswith("_")
                and _option_text(value) is not None
                and normalized not in discovered
            ):
                discovered.append(normalized)
    return tuple(discovered)


def _row_updated_at(row: object) -> datetime:
    values = [
        getattr(item, "updated_at", None)
        for item in row
        if item is not None
    ]
    return max((_as_utc(value) for value in values if value is not None), default=utcnow())


def _group_rows(rows: list[object]) -> list[list[object]]:
    grouped: dict[UUID, list[object]] = {}
    for row in rows:
        grouped.setdefault(row[2].id, []).append(row)
    return list(grouped.values())


def _product_source(rows: list[object]) -> dict[str, Any]:
    rows = sorted(rows, key=lambda row: str(row[1].id))
    _offer, _sku, product, category = rows[0]
    tags = _clean_tags(rows)
    specifications = tuple(
        dict.fromkeys(
            str((row[1].option_values or {}).get("规格名称") or "").strip()
            for row in rows
            if str((row[1].option_values or {}).get("规格名称") or "").strip()
        )
    )
    option_labels = _variant_option_keys(rows)
    option_values = tuple(
        dict.fromkeys(
            text
            for row in rows
            for label in option_labels
            if (text := _option_text((row[1].option_values or {}).get(label)))
        )
    )
    source = {
        "product_id": str(product.id),
        "name": str(product.name).strip(),
        "description": str(product.description or "").strip() or None,
        "category": _category_path(category),
        "tags": list(tags),
        "display_tag": _display_tag(rows, tags),
        "specifications": list(specifications),
        "option_labels": list(option_labels),
        "option_values": list(option_values),
        "product_version": int(product.current_version),
    }
    source["source_hash"] = _json_hash(source)
    source["source_updated_at"] = _iso(max(_row_updated_at(row) for row in rows))
    return source


def _sku_source(row: object) -> dict[str, Any]:
    offer, sku, product, category = row
    source = catalog_translation_source(row)
    specification = str((sku.option_values or {}).get("规格名称") or "").strip() or None
    package_source = {
        "sku_id": str(sku.id),
        "product_id": str(product.id),
        "name": source.name,
        "description": source.description,
        "category": source.category or _category_path(category),
        "tags": list(source.tags),
        "display_tag": source.display_tag,
        "specification": specification,
        "translation_source_hash": source.source_hash,
        "product_version": int(product.current_version),
        "sku_version": int(sku.version),
    }
    package_source["source_hash"] = _json_hash(package_source)
    package_source["source_updated_at"] = _iso(_row_updated_at(row))
    package_source["offer_updated_at"] = _iso(_as_utc(offer.updated_at))
    return package_source


def catalog_product_package_source_hash(rows: list[object]) -> str:
    return str(_product_source(rows)["source_hash"])


def catalog_sku_package_source_hash(row: object) -> str:
    return str(_sku_source(row)["source_hash"])


def catalog_language_pack_source_entries(
    rows: list[object],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Expose the canonical package sources for administration workflows."""

    groups = _group_rows(rows)
    return (
        [_product_source(group) for group in groups],
        [_sku_source(row) for row in rows],
    )


def catalog_language_pack_source_cutoff(rows: list[object]) -> datetime:
    return max((_row_updated_at(row) for row in rows), default=utcnow())


def catalog_language_pack_product_entry(source: dict[str, Any]) -> dict[str, Any]:
    """Build a source-language fallback entry with the current identity."""

    tags = list(source["tags"])
    return {
        "source_hash": source["source_hash"],
        "source_updated_at": source["source_updated_at"],
        "product_version": source["product_version"],
        "name": source["name"],
        "description": source["description"],
        "category_label": source["category"],
        "tags": tags,
        "display_tag": source["display_tag"],
        "specifications": {value: value for value in source["specifications"]},
        "option_labels": {value: value for value in source["option_labels"]},
        "option_values": {value: value for value in source["option_values"]},
    }


def catalog_language_pack_sku_entry(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_hash": source["source_hash"],
        "source_updated_at": source["source_updated_at"],
        "product_version": source["product_version"],
        "sku_version": source["sku_version"],
        "product_id": source["product_id"],
        "name": source["name"],
        "description": source["description"],
        "category_label": source["category"],
        "tags": list(source["tags"]),
        "display_tag": source["display_tag"],
        "specification": source["specification"],
    }


def _apply_entry_override(
    entry: dict[str, Any],
    *,
    source_hash: str,
    override: dict[str, Any] | None,
    allowed_fields: frozenset[str],
) -> bool:
    if not isinstance(override, dict) or override.get("source_hash") != source_hash:
        return False
    values = override.get("values")
    if not isinstance(values, dict):
        return False
    for field in allowed_fields:
        if field in values:
            entry[field] = values[field]
    # Identity always belongs to the source snapshot, never the override.
    entry["source_hash"] = source_hash
    return True


def apply_catalog_language_pack_overrides(
    *,
    products: dict[str, dict[str, Any]],
    skus: dict[str, dict[str, Any]],
    product_sources: list[dict[str, Any]],
    sku_sources: list[dict[str, Any]],
    product_overrides: dict[str, dict[str, Any]] | None,
    sku_overrides: dict[str, dict[str, Any]] | None,
) -> tuple[set[str], set[str]]:
    """Apply exact-source manual wording after automatic translation."""

    applied_products: set[str] = set()
    applied_skus: set[str] = set()
    product_overrides = product_overrides or {}
    sku_overrides = sku_overrides or {}
    product_fields = frozenset(
        {
            "name",
            "description",
            "category_label",
            "tags",
            "display_tag",
            "specifications",
            "option_labels",
            "option_values",
        }
    )
    sku_fields = frozenset(
        {
            "name",
            "description",
            "category_label",
            "tags",
            "display_tag",
            "specification",
        }
    )
    for source in product_sources:
        entry_id = source["product_id"]
        entry = products.get(entry_id)
        if entry is not None and _apply_entry_override(
            entry,
            source_hash=source["source_hash"],
            override=product_overrides.get(entry_id),
            allowed_fields=product_fields,
        ):
            applied_products.add(entry_id)
    for source in sku_sources:
        entry_id = source["sku_id"]
        entry = skus.get(entry_id)
        if entry is not None and _apply_entry_override(
            entry,
            source_hash=source["source_hash"],
            override=sku_overrides.get(entry_id),
            allowed_fields=sku_fields,
        ):
            applied_skus.add(entry_id)
    return applied_products, applied_skus


def catalog_language_pack_payload_matches_rows(
    payload: dict[str, Any],
    rows: list[object],
) -> bool:
    product_sources, sku_sources = catalog_language_pack_source_entries(rows)
    products = payload.get("products")
    skus = payload.get("skus")
    if not isinstance(products, dict) or not isinstance(skus, dict):
        return False
    if set(products) != {source["product_id"] for source in product_sources}:
        return False
    if set(skus) != {source["sku_id"] for source in sku_sources}:
        return False
    return all(
        isinstance(products.get(source["product_id"]), dict)
        and products[source["product_id"]].get("source_hash") == source["source_hash"]
        for source in product_sources
    ) and all(
        isinstance(skus.get(source["sku_id"]), dict)
        and skus[source["sku_id"]].get("source_hash") == source["source_hash"]
        for source in sku_sources
    )


def _translatable(value: str) -> bool:
    return bool(_CJK_TEXT.search(value) or _LATIN_WORD.search(value))


def _description_fragments(value: str | None) -> list[str]:
    if not value:
        return []
    return list(
        dict.fromkeys(
            content.strip()
            for content in value.splitlines()
            if content.strip() and _translatable(content.strip())
        )
    )


def _all_translatable_values(
    product_sources: list[dict[str, Any]],
    sku_sources: list[dict[str, Any]],
) -> list[str]:
    values: list[str] = []
    for source in product_sources:
        values.extend(
            value
            for value in [
                source["name"],
                *source["tags"],
                *source["specifications"],
                *source["option_labels"],
                *source["option_values"],
            ]
            if value and _translatable(value)
        )
        values.extend(_description_fragments(source["description"]))
        values.extend(
            segment
            for segment in str(source["category"] or "").replace("／", "/").split("/")
            if segment.strip() and _translatable(segment.strip())
        )
    for source in sku_sources:
        values.extend(
            value
            for value in [source["name"], *source["tags"]]
            if value and _translatable(value)
        )
        values.extend(_description_fragments(source["description"]))
        values.extend(
            segment
            for segment in str(source["category"] or "").replace("／", "/").split("/")
            if segment.strip() and _translatable(segment.strip())
        )
        if source["specification"] and _translatable(source["specification"]):
            values.append(source["specification"])
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def catalog_language_pack_translatable_values(rows: list[object]) -> list[str]:
    """Return the globally de-duplicated text corpus for a catalog snapshot."""

    groups = _group_rows(rows)
    return _all_translatable_values(
        [_product_source(group) for group in groups],
        [_sku_source(row) for row in rows],
    )


def _translation_seed(
    sku_sources: list[dict[str, Any]],
    rows_by_sku_id: dict[str, CatalogSkuTranslationRow],
) -> dict[str, str]:
    seed: dict[str, str] = {}
    for source in sku_sources:
        translated = rows_by_sku_id.get(source["sku_id"])
        if (
            translated is None
            or translated.source_hash != source["translation_source_hash"]
        ):
            continue
        pairs: list[tuple[str | None, str | None]] = [
            (source["name"], translated.name),
            (source["description"], translated.description),
            (source["category"], translated.category),
        ]
        pairs.extend(zip(source["tags"], translated.tags or [], strict=False))
        for raw, localized in pairs:
            if raw and localized and str(localized).strip():
                seed.setdefault(str(raw).strip(), str(localized).strip())
    return seed


def _seed_pair(
    seed: dict[str, str],
    source: object,
    translated: object,
) -> None:
    raw = str(source or "").strip()
    localized = str(translated or "").strip()
    if raw and localized:
        seed.setdefault(raw, localized)


def _seed_description(
    seed: dict[str, str],
    source: object,
    translated: object,
) -> None:
    raw = str(source or "")
    localized = str(translated or "")
    _seed_pair(seed, raw, localized)
    raw_lines = [line.strip() for line in raw.splitlines() if line.strip()]
    localized_lines = [
        line.strip() for line in localized.splitlines() if line.strip()
    ]
    if len(raw_lines) == len(localized_lines):
        for raw_line, localized_line in zip(
            raw_lines,
            localized_lines,
            strict=True,
        ):
            _seed_pair(seed, raw_line, localized_line)


def _seed_path(
    seed: dict[str, str],
    source: object,
    translated: object,
) -> None:
    raw = str(source or "").replace("／", "/")
    localized = str(translated or "").replace("／", "/")
    _seed_pair(seed, raw, localized)
    raw_segments = [segment.strip() for segment in raw.split("/") if segment.strip()]
    localized_segments = [
        segment.strip() for segment in localized.split("/") if segment.strip()
    ]
    if len(raw_segments) == len(localized_segments):
        for raw_segment, localized_segment in zip(
            raw_segments,
            localized_segments,
            strict=True,
        ):
            _seed_pair(seed, raw_segment, localized_segment)


def catalog_language_pack_translation_seed(
    rows: list[object],
    *,
    sku_translations: dict[UUID, CatalogSkuTranslationRow],
    previous_payload: dict[str, Any] | None,
    reuse_previous: bool,
) -> dict[str, str]:
    """Recover exact-text translations from valid rows and the active pack.

    Batch jobs use this before submitting a file, so changing execution modes
    never makes unchanged catalog text start again from zero.
    """

    groups = _group_rows(rows)
    product_sources = [_product_source(group) for group in groups]
    sku_sources = [_sku_source(row) for row in rows]
    seed = _translation_seed(
        sku_sources,
        {str(sku_id): row for sku_id, row in sku_translations.items()},
    )
    if not reuse_previous or not isinstance(previous_payload, dict):
        return seed

    previous_products = previous_payload.get("products")
    previous_skus = previous_payload.get("skus")
    previous_products = (
        previous_products if isinstance(previous_products, dict) else {}
    )
    previous_skus = previous_skus if isinstance(previous_skus, dict) else {}

    for source in product_sources:
        translated = previous_products.get(source["product_id"])
        if (
            not isinstance(translated, dict)
            or translated.get("source_hash") != source["source_hash"]
        ):
            continue
        _seed_pair(seed, source["name"], translated.get("name"))
        _seed_description(
            seed,
            source["description"],
            translated.get("description"),
        )
        _seed_path(
            seed,
            source["category"],
            translated.get("category_label"),
        )
        for raw, localized in zip(
            source["tags"],
            translated.get("tags") or [],
            strict=False,
        ):
            _seed_pair(seed, raw, localized)
        for field in ("specifications", "option_labels", "option_values"):
            localized_values = translated.get(field)
            if not isinstance(localized_values, dict):
                continue
            for raw in source[field]:
                _seed_pair(seed, raw, localized_values.get(raw))

    for source in sku_sources:
        translated = previous_skus.get(source["sku_id"])
        if (
            not isinstance(translated, dict)
            or translated.get("source_hash") != source["source_hash"]
        ):
            continue
        _seed_pair(seed, source["name"], translated.get("name"))
        _seed_description(
            seed,
            source["description"],
            translated.get("description"),
        )
        _seed_path(
            seed,
            source["category"],
            translated.get("category_label"),
        )
        for raw, localized in zip(
            source["tags"],
            translated.get("tags") or [],
            strict=False,
        ):
            _seed_pair(seed, raw, localized)
        _seed_pair(
            seed,
            source["specification"],
            translated.get("specification"),
        )
    return seed


def _translate_missing_values(
    *,
    tenant_id: UUID,
    translator: TranslationProvider,
    values: list[str],
    source_locale: str,
    target_locale: str,
    seed: dict[str, str],
) -> dict[str, str]:
    translated = dict(seed)
    missing = [value for value in values if value not in translated]
    grouped: dict[str, list[str]] = {}
    for value in missing:
        value_source_locale = source_locale if _CJK_TEXT.search(value) else "en-US"
        if value_source_locale == target_locale:
            translated[value] = value
        else:
            grouped.setdefault(value_source_locale, []).append(value)
    for value_source_locale, group in grouped.items():
        translated.update(
            translate_values_with_memory(
                tenant_id=tenant_id,
                translator=translator,
                values=group,
                source_locale=value_source_locale,
                target_locale=target_locale,
            )
        )
    unresolved = [value for value in values if value not in translated]
    if unresolved:
        raise TranslationProviderError(
            f"language package translation left {len(unresolved)} fields incomplete",
            recover_with_smaller_batches=True,
        )
    return translated


def _localized_value(value: str | None, translations: dict[str, str]) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or not _translatable(normalized):
        return value
    return translations.get(normalized, value)


def _localized_description(value: str | None, translations: dict[str, str]) -> str | None:
    if value is None:
        return None
    if value.strip() in translations:
        return translations[value.strip()]
    return "\n".join(
        translations.get(line.strip(), line) if line.strip() else line
        for line in value.splitlines()
    )


def _localized_path(value: str | None, translations: dict[str, str]) -> str | None:
    if not value:
        return None
    if value.strip() in translations:
        return translations[value.strip()]
    return "/".join(
        translations.get(segment.strip(), segment.strip())
        for segment in value.replace("／", "/").split("/")
        if segment.strip()
    ) or None


def _localized_tags(
    tags: list[str],
    display_tag: str | None,
    translations: dict[str, str],
) -> tuple[list[str], str | None]:
    localized = list(
        dict.fromkeys(
            translations.get(tag, tag)
            for tag in tags
            if tag.strip()
        )
    )
    display_index = next(
        (
            index
            for index, tag in enumerate(tags)
            if display_tag and tag.casefold() == display_tag.casefold()
        ),
        None,
    )
    localized_display = (
        localized[display_index]
        if display_index is not None and display_index < len(localized)
        else localized[0] if localized else None
    )
    return localized, localized_display


def _reusable_entry(
    previous: dict[str, Any] | None,
    *,
    entry_id: str,
    source_hash: str,
) -> dict[str, Any] | None:
    if not previous:
        return None
    entry = previous.get(entry_id)
    if not isinstance(entry, dict) or entry.get("source_hash") != source_hash:
        return None
    return dict(entry)


def load_language_pack_payload(
    storage: LanguagePackageStorage,
    row: CatalogLanguagePackRow | None,
) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        raw = gzip.decompress(storage.get(row.object_key))
        if hashlib.sha256(raw).hexdigest() != row.content_sha256:
            raise ValueError("language package checksum mismatch")
        payload = json.loads(raw)
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != PACKAGE_SCHEMA
            or payload.get("schema_version") != PACKAGE_SCHEMA_VERSION
            or payload.get("target_locale") != row.target_locale
        ):
            raise ValueError("language package schema mismatch")
        return payload
    except Exception as exc:
        logger.warning("could not reuse previous language package: %s", exc)
        return None


def build_catalog_language_pack(
    *,
    tenant_id: UUID,
    rows: list[object],
    source_locale: str,
    target_locale: str,
    version: int,
    translator: TranslationProvider,
    sku_translations: dict[UUID, CatalogSkuTranslationRow],
    previous_payload: dict[str, Any] | None,
    reuse_previous: bool = False,
    full_rebuild: bool,
    force_rebuild_sku_ids: set[UUID] | None = None,
    product_overrides: dict[str, dict[str, Any]] | None = None,
    sku_overrides: dict[str, dict[str, Any]] | None = None,
) -> CatalogLanguagePackBuild:
    groups = _group_rows(rows)
    product_sources = [_product_source(group) for group in groups]
    sku_sources = [_sku_source(row) for row in rows]
    previous_compatible = bool(
        isinstance(previous_payload, dict)
        and reuse_previous
    )
    previous_products = (
        previous_payload.get("products")
        if previous_compatible and not full_rebuild
        else None
    )
    previous_skus = (
        previous_payload.get("skus")
        if previous_compatible and not full_rebuild
        else None
    )
    previous_products = previous_products if isinstance(previous_products, dict) else None
    previous_skus = previous_skus if isinstance(previous_skus, dict) else None

    # A manual product retranslation can have the same source hash as the
    # currently published package. Do not reuse those entries, otherwise the
    # newly saved translation rows would never make it into the next file.
    forced_sku_ids = {str(value) for value in (force_rebuild_sku_ids or set())}
    forced_product_ids = {
        source["product_id"]
        for source in sku_sources
        if source["sku_id"] in forced_sku_ids
    }

    changed_products = [
        source
        for source in product_sources
        if _reusable_entry(
            previous_products,
            entry_id=source["product_id"],
            source_hash=source["source_hash"],
        ) is None
        or source["product_id"] in forced_product_ids
    ]
    changed_skus = [
        source
        for source in sku_sources
        if _reusable_entry(
            previous_skus,
            entry_id=source["sku_id"],
            source_hash=source["source_hash"],
        ) is None
        or source["sku_id"] in forced_sku_ids
    ]
    rows_by_sku_id = {
        str(sku_id): translation
        for sku_id, translation in sku_translations.items()
    }
    # Exact text can be shared by multiple SKUs and products. Seed from the
    # complete current catalog, not only entries whose package hash changed.
    # Otherwise an updated product can lose a name/specification that already
    # has a valid translation on an unchanged sibling or duplicate SKU, and
    # packaging incorrectly asks the provider to translate it again.
    seed = _translation_seed(sku_sources, rows_by_sku_id)
    values = _all_translatable_values(changed_products, changed_skus)
    translations = _translate_missing_values(
        tenant_id=tenant_id,
        translator=translator,
        values=values,
        source_locale=source_locale,
        target_locale=target_locale,
        seed=seed,
    )

    products: dict[str, dict[str, Any]] = {}
    for source in product_sources:
        reusable = _reusable_entry(
            previous_products,
            entry_id=source["product_id"],
            source_hash=source["source_hash"],
        )
        if source["product_id"] in forced_product_ids:
            reusable = None
        if reusable is not None:
            products[source["product_id"]] = reusable
            continue
        localized_tags, localized_display = _localized_tags(
            source["tags"], source["display_tag"], translations
        )
        products[source["product_id"]] = {
            "source_hash": source["source_hash"],
            "source_updated_at": source["source_updated_at"],
            "product_version": source["product_version"],
            "name": _localized_value(source["name"], translations),
            "description": _localized_description(source["description"], translations),
            "category_label": _localized_path(source["category"], translations),
            "tags": localized_tags,
            "display_tag": localized_display,
            "specifications": {
                value: _localized_value(value, translations) or value
                for value in source["specifications"]
            },
            "option_labels": {
                value: _localized_value(value, translations) or value
                for value in source["option_labels"]
            },
            "option_values": {
                value: _localized_value(value, translations) or value
                for value in source["option_values"]
            },
        }

    skus: dict[str, dict[str, Any]] = {}
    for source in sku_sources:
        reusable = _reusable_entry(
            previous_skus,
            entry_id=source["sku_id"],
            source_hash=source["source_hash"],
        )
        if source["sku_id"] in forced_sku_ids:
            reusable = None
        if reusable is not None:
            skus[source["sku_id"]] = reusable
            continue
        localized_tags, localized_display = _localized_tags(
            source["tags"], source["display_tag"], translations
        )
        skus[source["sku_id"]] = {
            "source_hash": source["source_hash"],
            "source_updated_at": source["source_updated_at"],
            "product_version": source["product_version"],
            "sku_version": source["sku_version"],
            "product_id": source["product_id"],
            "name": _localized_value(source["name"], translations),
            "description": _localized_description(source["description"], translations),
            "category_label": _localized_path(source["category"], translations),
            "tags": localized_tags,
            "display_tag": localized_display,
            "specification": _localized_value(source["specification"], translations),
        }

    apply_catalog_language_pack_overrides(
        products=products,
        skus=skus,
        product_sources=product_sources,
        sku_sources=sku_sources,
        product_overrides=product_overrides,
        sku_overrides=sku_overrides,
    )

    categories = {
        source["category"]: products[source["product_id"]].get("category_label")
        or source["category"]
        for source in product_sources
        if source["category"]
    }
    source_digest = _catalog_sources_digest(product_sources, sku_sources)
    source_cutoff_at = max(
        (_row_updated_at(row) for row in rows),
        default=utcnow(),
    )
    generated_at = utcnow()
    payload: dict[str, Any] = {
        "schema": PACKAGE_SCHEMA,
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "source_locale": source_locale,
        "target_locale": target_locale,
        "version": version,
        "generated_at": _iso(generated_at),
        "source_cutoff_at": _iso(source_cutoff_at),
        "products": products,
        "skus": skus,
        "categories": categories,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    content_sha256 = hashlib.sha256(raw).hexdigest()
    return CatalogLanguagePackBuild(
        payload=payload,
        compressed=gzip.compress(raw, compresslevel=6, mtime=0),
        content_sha256=content_sha256,
        source_digest=source_digest,
        source_cutoff_at=source_cutoff_at,
        product_count=len(products),
        sku_count=len(skus),
        category_count=len(categories),
    )


def repack_catalog_language_pack_payload(
    payload: dict[str, Any],
    *,
    version: int,
    source_digest: str,
    source_cutoff_at: datetime,
) -> CatalogLanguagePackBuild:
    """Create a new immutable package version from reviewed administrator edits."""

    payload["version"] = version
    payload["generated_at"] = _iso(utcnow())
    payload["source_cutoff_at"] = _iso(source_cutoff_at)
    products = payload.get("products")
    skus = payload.get("skus")
    categories = payload.get("categories")
    products = products if isinstance(products, dict) else {}
    skus = skus if isinstance(skus, dict) else {}
    categories = categories if isinstance(categories, dict) else {}
    payload["products"] = products
    payload["skus"] = skus
    payload["categories"] = categories
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return CatalogLanguagePackBuild(
        payload=payload,
        compressed=gzip.compress(raw, compresslevel=6, mtime=0),
        content_sha256=hashlib.sha256(raw).hexdigest(),
        source_digest=source_digest,
        source_cutoff_at=source_cutoff_at,
        product_count=len(products),
        sku_count=len(skus),
        category_count=len(categories),
    )


def language_pack_object_key(
    *,
    tenant_id: UUID,
    target_locale: str,
    version: int,
    content_sha256: str,
) -> str:
    safe_locale = re.sub(r"[^A-Za-z0-9-]", "-", target_locale)
    return (
        f"translations/{tenant_id}/{safe_locale}/"
        f"catalog-v{version}-{content_sha256[:16]}.json.gz"
    )
