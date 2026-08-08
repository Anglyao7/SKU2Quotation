from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from uuid import UUID

from .translation import TranslationProvider, TranslationProviderError


_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?=[A-Za-z0-9._/+%\-\uFF0D]{2,})"
    r"(?=[A-Za-z0-9._/+%\-\uFF0D]*[A-Za-z])"
    r"(?=[A-Za-z0-9._/+%\-\uFF0D]*\d)"
    r"[A-Za-z0-9][A-Za-z0-9._/+%\-\uFF0D]*"
)
_FIELD_MARKER_PATTERN = re.compile(
    r"\[+\s*ATCF[\s_-]*(?P<item>\d{3})[\s_-]+"
    r"(?P<field>\d{3})\s*\]+",
    re.IGNORECASE,
)
_VALUE_MARKER_PATTERN = re.compile(
    r"\[+\s*ATCV[\s_-]*(?P<item>\d{3})\s*\]+",
    re.IGNORECASE,
)
_PROTECTED_MARKER_PATTERN = re.compile(
    r"\[+\s*ATCK[\s_-]*(?P<item>\d{5})\s*\]+",
    re.IGNORECASE,
)
_TRANSLATABLE_PROSE_PATTERN = re.compile(r"[A-Za-z]{2,}|[\u3400-\u9fff]")
_CJK_PROSE_PATTERN = re.compile(r"[\u3400-\u9fff]")


def catalog_translation_value_is_complete(
    source_value: str,
    translated_value: str,
    *,
    source_locale: str,
    target_locale: str,
) -> bool:
    """Reject visibly partial storefront translations.

    Product codes and dimensions may remain unchanged, but Chinese prose must
    not leak into Latin, Arabic, or Korean storefronts. Japanese legitimately
    uses Han characters, so for Japanese we only reject a wholly unchanged
    Chinese value. This check is also used when reading translation memory so
    an older partial response cannot remain stuck in the storefront cache.
    """

    source = source_value.strip()
    translated = translated_value.strip()
    if not translated:
        return False
    if source_locale == target_locale or not _CJK_PROSE_PATTERN.search(source):
        return True

    normalized_target = target_locale.strip().replace("_", "-").casefold()
    if normalized_target in {"zh", "zh-cn"}:
        return True
    if normalized_target in {"ja", "ja-jp"}:
        return translated.casefold() != source.casefold()
    return not _CJK_PROSE_PATTERN.search(translated)


@dataclass(frozen=True)
class CatalogTranslationSource:
    sku_id: UUID
    sku_code: str
    name: str
    description: str | None
    category: str | None
    tags: tuple[str, ...]
    display_tag: str | None
    product_version: int
    sku_version: int
    source_hash: str


@dataclass(frozen=True)
class CatalogTranslationResult:
    sku_id: UUID
    source_hash: str
    name: str
    description: str | None
    category: str | None
    tags: tuple[str, ...]
    display_tag: str | None
    complete: bool = True


def _category_path(category: object | None) -> str:
    if category is None:
        return ""
    path = str(getattr(category, "path", "") or "").strip()
    name = str(getattr(category, "name", "") or "").strip()
    code = str(getattr(category, "code", "") or "").strip()
    if path and code and path.casefold() == code.casefold():
        return name
    return path or name


def catalog_translation_source(row: object) -> CatalogTranslationSource:
    offer, sku, product, category = row
    tags = tuple(
        dict.fromkeys(
            str(tag).strip()
            for tag in (offer.tags or [])
            if str(tag).strip()
        )
    )
    tag_lookup = {tag.casefold(): tag for tag in tags}
    requested_display_tag = str(offer.display_tag or "").strip()
    display_tag = (
        tag_lookup.get(requested_display_tag.casefold())
        if requested_display_tag
        else None
    ) or (tags[0] if tags else None)
    source = {
        "sku_code": str(sku.sku_code).strip(),
        "name": str(sku.name or product.name).strip(),
        "description": str(product.description or "").strip() or None,
        "category": _category_path(category) or None,
        "tags": list(tags),
        "display_tag": display_tag,
        "product_version": int(product.current_version),
        "sku_version": int(sku.version),
    }
    source_hash = hashlib.sha256(
        json.dumps(
            source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return CatalogTranslationSource(
        sku_id=sku.id,
        sku_code=source["sku_code"],
        name=source["name"],
        description=source["description"],
        category=source["category"],
        tags=tags,
        display_tag=display_tag,
        product_version=source["product_version"],
        sku_version=source["sku_version"],
        source_hash=source_hash,
    )


def catalog_translation_source_size(source: CatalogTranslationSource) -> int:
    return sum(
        len(value)
        for value in (
            source.name,
            source.description or "",
            source.category or "",
            *source.tags,
        )
    )


def translation_batches(
    sources: list[CatalogTranslationSource],
    *,
    max_items: int,
    max_characters: int,
) -> list[list[CatalogTranslationSource]]:
    if max_items < 1 or max_characters < 1:
        raise ValueError("translation batch limits must be positive")
    batches: list[list[CatalogTranslationSource]] = []
    current: list[CatalogTranslationSource] = []
    current_size = 0
    for source in sources:
        source_size = catalog_translation_source_size(source)
        if current and (
            len(current) >= max_items
            or current_size + source_size > max_characters
        ):
            batches.append(current)
            current = []
            current_size = 0
        current.append(source)
        current_size += source_size
    if current:
        batches.append(current)
    return batches


def _protect_identifiers(
    value: str,
    *,
    protected: dict[str, str],
) -> str:
    def replace(match: re.Match[str]) -> str:
        literal = match.group(0)
        placeholder = f"[[ATCK_{len(protected):05d}]]"
        protected[placeholder] = literal
        return placeholder

    return _IDENTIFIER_PATTERN.sub(replace, value)


def _restore_identifiers(
    value: str,
    *,
    protected: dict[str, str],
) -> str:
    def replace(match: re.Match[str]) -> str:
        placeholder = f"[[ATCK_{int(match.group('item')):05d}]]"
        return protected.get(placeholder, match.group(0))

    return _PROTECTED_MARKER_PATTERN.sub(replace, value).strip()


def _field_values(source: CatalogTranslationSource) -> dict[str, str]:
    values = {"NAME": source.name}
    if source.description:
        values["DESCRIPTION"] = source.description
    if source.category:
        segments = [
            segment.strip()
            for segment in source.category.replace("／", "/").split("/")
            if segment.strip()
        ]
        for index, segment in enumerate(segments):
            values[f"CATEGORY_{index:03d}"] = segment
    for index, tag in enumerate(source.tags):
        values[f"TAG_{index:03d}"] = tag
    return values


def translate_catalog_sources(
    translator: TranslationProvider,
    sources: list[CatalogTranslationSource],
    *,
    source_locale: str,
    target_locale: str,
) -> list[CatalogTranslationResult]:
    if not sources:
        return []
    if len(sources) > 999:
        raise ValueError("a translation batch cannot contain more than 999 SKUs")

    protected: dict[str, str] = {}
    expected_fields: dict[int, dict[str, str]] = {}
    field_names: dict[tuple[int, int], str] = {}
    payload_lines: list[str] = []
    for item_index, source in enumerate(sources):
        fields = _field_values(source)
        expected_fields[item_index] = fields
        for field_index, (field, value) in enumerate(fields.items()):
            field_names[(item_index, field_index)] = field
            payload_lines.append(
                f"[[ATCF_{item_index:03d}_{field_index:03d}]]"
            )
            payload_lines.append(
                _protect_identifiers(value, protected=protected)
            )

    translated_text = translator.translate(
        "\n".join(payload_lines),
        source_locale=source_locale,
        target_locale=target_locale,
    )
    marker_matches = list(_FIELD_MARKER_PATTERN.finditer(translated_text))
    translated_fields: dict[tuple[int, str], str] = {}
    for index, match in enumerate(marker_matches):
        start = match.end()
        end = (
            marker_matches[index + 1].start()
            if index + 1 < len(marker_matches)
            else len(translated_text)
        )
        item_index = int(match.group("item"))
        field_index = int(match.group("field"))
        field = field_names.get((item_index, field_index))
        if field is None:
            continue
        translated_fields[(item_index, field)] = _restore_identifiers(
            translated_text[start:end],
            protected=protected,
        )

    results: list[CatalogTranslationResult] = []
    for item_index, source in enumerate(sources):
        expected = expected_fields[item_index]
        missing = [
            field
            for field in expected
            if not translated_fields.get((item_index, field), "").strip()
        ]
        if missing:
            raise TranslationProviderError(
                "translation provider did not preserve the catalog field structure",
                recover_with_smaller_batches=True,
            )
        name = translated_fields[(item_index, "NAME")].strip()
        description = (
            translated_fields[(item_index, "DESCRIPTION")].strip()
            if "DESCRIPTION" in expected
            else None
        )
        category_segments = [
            translated_fields[(item_index, field)].strip()
            for field in expected
            if field.startswith("CATEGORY_")
        ]
        translated_tags = tuple(
            dict.fromkeys(
                translated_fields[(item_index, field)].strip()
                for field in expected
                if field.startswith("TAG_")
                and translated_fields[(item_index, field)].strip()
            )
        )
        display_tag_index = next(
            (
                index
                for index, tag in enumerate(source.tags)
                if source.display_tag
                and tag.casefold() == source.display_tag.casefold()
            ),
            None,
        )
        display_tag = (
            translated_fields.get(
                (item_index, f"TAG_{display_tag_index:03d}"),
            )
            if display_tag_index is not None
            else None
        ) or (translated_tags[0] if translated_tags else None)
        results.append(
            CatalogTranslationResult(
                sku_id=source.sku_id,
                source_hash=source.source_hash,
                name=name,
                description=description,
                category="/".join(category_segments) or None,
                tags=translated_tags,
                display_tag=display_tag.strip() if display_tag else None,
            )
        )
    return results


def translate_catalog_values(
    translator: TranslationProvider,
    values: list[str],
    *,
    source_locale: str,
    target_locale: str,
) -> list[str]:
    """Translate a bounded list while preserving its exact item boundaries."""

    if not values:
        return []
    if len(values) > 999:
        raise ValueError("a translation request cannot contain more than 999 values")

    protected: dict[str, str] = {}
    payload_lines: list[str] = []
    for item_index, value in enumerate(values):
        payload_lines.append(f"[[ATCV_{item_index:03d}]]")
        payload_lines.append(_protect_identifiers(value, protected=protected))

    translated_text = translator.translate(
        "\n".join(payload_lines),
        source_locale=source_locale,
        target_locale=target_locale,
    )
    matches = list(_VALUE_MARKER_PATTERN.finditer(translated_text))
    translated: dict[int, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(
            translated_text
        )
        translated[int(match.group("item"))] = _restore_identifiers(
            translated_text[start:end],
            protected=protected,
        )

    missing = [
        item_index
        for item_index in range(len(values))
        if not translated.get(item_index, "").strip()
    ]
    if missing:
        raise TranslationProviderError(
            "translation provider did not preserve the catalog value structure",
            recover_with_smaller_batches=True,
        )
    results = [
        translated[item_index].strip()
        for item_index in range(len(values))
    ]
    if source_locale != target_locale:
        for item_index, (source_value, translated_value) in enumerate(
            zip(values, results, strict=True)
        ):
            normalized_source = source_value.strip()
            needs_direct_retry = (
                _TRANSLATABLE_PROSE_PATTERN.search(normalized_source)
                and (
                    translated_value.casefold() == normalized_source.casefold()
                    or not catalog_translation_value_is_complete(
                        normalized_source,
                        translated_value,
                        source_locale=source_locale,
                        target_locale=target_locale,
                    )
                )
            )
            if not needs_direct_retry:
                continue
            direct_protected: dict[str, str] = {}
            direct_source = _protect_identifiers(
                normalized_source,
                protected=direct_protected,
            )
            try:
                direct_translation = translator.translate(
                    direct_source,
                    source_locale=source_locale,
                    target_locale=target_locale,
                )
            except TranslationProviderError:
                continue
            restored = _restore_identifiers(
                direct_translation,
                protected=direct_protected,
            )
            if restored:
                results[item_index] = restored
        incomplete = [
            item_index
            for item_index, (source_value, translated_value) in enumerate(
                zip(values, results, strict=True)
            )
            if not catalog_translation_value_is_complete(
                source_value,
                translated_value,
                source_locale=source_locale,
                target_locale=target_locale,
            )
        ]
        if incomplete:
            raise TranslationProviderError(
                "translation provider left source-language catalog text untranslated",
                recover_with_smaller_batches=True,
            )
    return results
