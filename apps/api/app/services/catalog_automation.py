"""Text-only change planning; never invalidates historical translation hashes."""
import hashlib
import json

from .catalog_language_packages import catalog_language_pack_source_entries

_METADATA = {"source_hash", "translation_source_hash", "product_version", "sku_version", "source_updated_at", "offer_updated_at"}


def text_source_snapshot(rows: list[object]) -> dict[str, str]:
    products, skus = catalog_language_pack_source_entries(rows)
    products_by_id = {source["product_id"]: source for source in products}
    result = {}
    for source in skus:
        content = [{key: value for key, value in entry.items() if key not in _METADATA}
                   for entry in (products_by_id[source["product_id"]], source)]
        encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        result[source["sku_id"]] = hashlib.sha256(encoded.encode()).hexdigest()
    return result


def changed_source_ids(previous: dict[str, str], current: dict[str, str]) -> list[str]:
    return sorted(key for key, value in current.items() if previous.get(key) != value)
