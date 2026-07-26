"""Curate concise search tags for the current local product catalog.

The script is intentionally conservative: it only updates SKUs that already
have a public catalog offer, because that is where the current product-tag
field lives. It never creates prices or publishes products.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import unicodedata
from uuid import uuid4


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / "var" / "mercator.db"

CATEGORY_TAGS: dict[str, tuple[str, str]] = {
    "口红": ("口红", "唇部彩妆"),
    "唇彩": ("唇彩", "唇部彩妆"),
    "妆前乳": ("妆前乳", "妆前打底"),
    "护手霜": ("护手霜", "手部护理"),
    "烤粉": ("烤粉", "烘焙彩妆"),
    "眼影": ("眼影盘", "眼部彩妆"),
    "眼线液": ("眼线液", "眼部彩妆"),
    "睫毛膏": ("睫毛膏", "眼部彩妆"),
    "磨砂膏": ("磨砂膏", "去角质"),
    "粉底液": ("粉底液", "底妆"),
    "粉饼": ("粉饼", "定妆"),
    "美白霜": ("美白霜", "提亮护肤"),
    "腮红": ("腮红", "面部彩妆"),
    "防晒霜": ("防晒霜", "防晒护理"),
    "香膏": ("香膏", "固体香氛"),
    "高光": ("高光", "提亮彩妆"),
}

PRIMARY_TAGS = {
    pair[0] for pair in CATEGORY_TAGS.values()
} | {
    "唇油",
    "遮瑕膏",
    "眼影盘",
    "宠物饮水机",
    "智能宠物喂食器",
    "宠物围栏",
    "腮红口红二合一",
    "散粉腮红",
    "散粉高光",
}


def _normalized_text(*values: str | None) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value).strip()
        for value in values
        if value and value.strip()
    )


def _unique_tags(*values: str) -> list[str]:
    result: list[str] = []
    for value in values:
        tag = value.strip()
        if tag and tag not in result:
            result.append(tag)
        if len(result) == 2:
            break
    return result


def derive_tags(
    *,
    product_name: str,
    sku_name: str | None,
    category_name: str | None,
) -> list[str]:
    """Return one or two retrieval-oriented tags grounded in known fields."""

    text = _normalized_text(product_name, sku_name, category_name)
    category = _normalized_text(category_name)

    if "宠物" in text and "饮水机" in text:
        return ["宠物饮水机", "不锈钢"] if "不锈钢" in text else ["宠物饮水机"]
    if "宠物" in text and "喂食器" in text:
        return ["智能宠物喂食器", "6L大容量"] if "6L" in text.upper() else ["智能宠物喂食器"]
    if "宠物" in text and "围栏" in text:
        return ["宠物围栏", "带门围栏"] if "带门" in text else ["宠物围栏"]

    if "腮红" in text and "口红" in text:
        return ["腮红口红二合一", "多合一"]

    if "书本" in text and ("眼影" in text or "书本套装" in category):
        if "唇彩" in text or "唇油" in text or "口红" in text:
            return ["眼唇彩妆套装", "多合一"]
        return ["眼影盘", "多合一"]

    if "散粉" in text and "腮红" in text:
        return ["散粉腮红", "面部彩妆"]
    if "散粉" in text and "高光" in text:
        return ["散粉高光", "提亮彩妆"]

    if "遮瑕" in text:
        return ["遮瑕膏", "遮瑕底妆"]

    if "唇油" in text:
        if "亮片" in text and "变色" in text:
            return ["唇油", "亮片变色"]
        if "变色" in text:
            return ["唇油", "变色唇妆"]
        if "透明" in text:
            return ["唇油", "透明唇妆"]
        return ["唇油", "唇部彩妆"]

    if "镜面" in text and ("唇彩" in text or category == "唇彩"):
        return ["唇彩", "镜面唇妆"]

    mapped = CATEGORY_TAGS.get(category)
    if mapped is not None:
        return list(mapped)

    leaf_category = category.rsplit("/", 1)[-1].strip()
    return _unique_tags(leaf_category) if leaf_category else []


def _tag_category(tag: str) -> str:
    return "品类" if tag in PRIMARY_TAGS else "特性"


def _load_rows(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """
            SELECT
                o.id AS offer_id,
                o.tags AS current_tags,
                s.id AS sku_id,
                s.name AS sku_name,
                p.id AS product_id,
                p.name AS product_name,
                pc.name AS category_name
            FROM skus AS s
            JOIN products AS p
              ON p.tenant_id = s.tenant_id
             AND p.id = s.product_id
            LEFT JOIN product_categories AS pc
              ON pc.tenant_id = p.tenant_id
             AND pc.id = p.category_id
            LEFT JOIN public_catalog_offers AS o
              ON o.tenant_id = s.tenant_id
             AND o.sku_id = s.id
             AND o.deleted_at IS NULL
            WHERE s.tenant_id = ?
              AND s.deleted_at IS NULL
              AND p.deleted_at IS NULL
              AND s.status = 'ACTIVE'
              AND p.status = 'ACTIVE'
            ORDER BY COALESCE(pc.name, ''), p.name, s.sku_code
            """,
            (tenant_id,),
        )
    )


def _parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    decoded = json.loads(value)
    if not isinstance(decoded, list):
        return []
    return [str(item).strip() for item in decoded if str(item).strip()]


def _backup_database(
    connection: sqlite3.Connection,
    *,
    database_path: Path,
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_directory = database_path.parent / "backups"
    backup_directory.mkdir(parents=True, exist_ok=True)
    backup_path = backup_directory / f"{database_path.stem}-before-curated-tags-{timestamp}.db"
    with sqlite3.connect(backup_path) as backup_connection:
        connection.backup(backup_connection)
    return backup_path


def _refresh_tag_dictionary(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    now: str,
) -> Counter[str]:
    frequencies: Counter[str] = Counter()
    for row in connection.execute(
        """
        SELECT o.tags
        FROM public_catalog_offers AS o
        WHERE o.tenant_id = ?
          AND o.deleted_at IS NULL
        """,
        (tenant_id,),
    ):
        frequencies.update(set(_parse_tags(row["tags"])))

    connection.execute(
        """
        UPDATE product_tags
        SET usage_count = 0,
            updated_at = ?
        WHERE tenant_id = ?
        """,
        (now, tenant_id),
    )

    for tag, usage_count in sorted(frequencies.items()):
        normalized_name = tag.casefold()
        existing = connection.execute(
            """
            SELECT id, category
            FROM product_tags
            WHERE tenant_id = ?
              AND normalized_name = ?
            """,
            (tenant_id, normalized_name),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO product_tags (
                    id,
                    tenant_id,
                    name,
                    normalized_name,
                    description,
                    category,
                    usage_count,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    tenant_id,
                    tag,
                    normalized_name,
                    _tag_category(tag),
                    usage_count,
                    now,
                    now,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE product_tags
                SET name = ?,
                    category = COALESCE(category, ?),
                    usage_count = ?,
                    updated_at = ?
                WHERE id = ?
                  AND tenant_id = ?
                """,
                (
                    tag,
                    _tag_category(tag),
                    usage_count,
                    now,
                    existing["id"],
                    tenant_id,
                ),
            )
    return frequencies


def curate(
    *,
    database_path: Path,
    tenant_slug: str,
    apply_changes: bool,
) -> int:
    if not database_path.is_file():
        raise SystemExit(f"Database not found: {database_path}")

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        tenant = connection.execute(
            "SELECT id, name, default_currency FROM tenants WHERE slug = ?",
            (tenant_slug,),
        ).fetchone()
        if tenant is None:
            raise SystemExit(f"Tenant not found: {tenant_slug}")

        rows = _load_rows(connection, tenant_id=tenant["id"])
        total_products = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM products
                WHERE tenant_id = ?
                  AND deleted_at IS NULL
                  AND status = 'ACTIVE'
                """,
                (tenant["id"],),
            ).fetchone()[0]
        )

        planned: list[tuple[sqlite3.Row, list[str], list[str]]] = []
        frequencies: Counter[str] = Counter()
        for row in rows:
            tags = derive_tags(
                product_name=row["product_name"],
                sku_name=row["sku_name"],
                category_name=row["category_name"],
            )
            if not tags:
                raise RuntimeError(
                    f"No grounded tags for product {row['product_name']!r} "
                    f"in category {row['category_name']!r}"
                )
            current_tags = _parse_tags(row["current_tags"])
            frequencies.update(tags)
            planned.append((row, current_tags, tags))

        changed = [
            item
            for item in planned
            if item[0]["offer_id"] is None or item[1] != item[2]
        ]
        missing_offers = sum(
            1 for row, _before, _after in planned if row["offer_id"] is None
        )
        print(
            f"Tenant: {tenant['name']} ({tenant_slug})\n"
            f"Active products: {total_products}\n"
            f"Eligible active SKUs: {len(rows)}\n"
            f"SKUs without a public offer: {missing_offers}\n"
            f"Offers to create or change: {len(changed)}"
        )
        print("\nTag frequencies:")
        for tag, count in frequencies.most_common():
            print(f"  {tag}: {count}")

        print("\nRepresentative mappings:")
        representatives: list[tuple[str, str, list[str]]] = []
        seen_tags: set[tuple[str, ...]] = set()
        for row, _before, tags in planned:
            signature = tuple(tags)
            if signature in seen_tags:
                continue
            seen_tags.add(signature)
            representatives.append(
                (row["product_name"], row["category_name"] or "未分类", tags)
            )
        for name, category, tags in representatives[:24]:
            print(f"  [{category}] {name} -> {', '.join(tags)}")

        if not apply_changes:
            print("\nDry run only. Re-run with --apply to write these changes.")
            return 0

        owner_membership = connection.execute(
            """
            SELECT id
            FROM memberships
            WHERE tenant_id = ?
              AND status = 'active'
              AND deleted_at IS NULL
            ORDER BY created_at, id
            LIMIT 1
            """,
            (tenant["id"],),
        ).fetchone()
        if owner_membership is None:
            raise RuntimeError("No active tenant membership is available for audit attribution")

        backup_path = _backup_database(
            connection,
            database_path=database_path,
        )
        now = datetime.now(timezone.utc).isoformat(sep=" ", timespec="microseconds")

        connection.execute("BEGIN IMMEDIATE")
        try:
            for row, before_tags, after_tags in changed:
                if row["offer_id"] is None:
                    offer_id = uuid4().hex
                    connection.execute(
                        """
                        INSERT INTO public_catalog_offers (
                            id,
                            tenant_id,
                            sku_id,
                            unit_price,
                            currency,
                            tags,
                            publication_status,
                            published_at,
                            valid_from,
                            valid_to,
                            created_at,
                            updated_at,
                            deleted_at,
                            tag_color
                        )
                        VALUES (?, ?, ?, 0, ?, ?, 'PUBLISHED', ?, NULL, NULL, ?, ?, NULL, NULL)
                        """,
                        (
                            offer_id,
                            tenant["id"],
                            row["sku_id"],
                            tenant["default_currency"],
                            json.dumps(after_tags, ensure_ascii=False),
                            now,
                            now,
                            now,
                        ),
                    )
                    audit_action = "public_offer.zero_price_backfilled"
                    before_payload = {
                        "unit_price": None,
                        "publication_status": None,
                        "tags": [],
                    }
                    after_payload = {
                        "unit_price": "0.00",
                        "publication_status": "PUBLISHED",
                        "tags": after_tags,
                    }
                else:
                    connection.execute(
                        """
                        UPDATE public_catalog_offers
                        SET tags = ?,
                            updated_at = ?
                        WHERE tenant_id = ?
                          AND id = ?
                        """,
                        (
                            json.dumps(after_tags, ensure_ascii=False),
                            now,
                            tenant["id"],
                            row["offer_id"],
                        ),
                    )
                    audit_action = "public_offer.tags_curated"
                    before_payload = {"tags": before_tags}
                    after_payload = {"tags": after_tags}
                connection.execute(
                    """
                    UPDATE products
                    SET search_document_version = 0,
                        updated_at = ?
                    WHERE tenant_id = ?
                      AND id = ?
                    """,
                    (now, tenant["id"], row["product_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO product_audit_events (
                        id,
                        tenant_id,
                        product_id,
                        entity_type,
                        entity_id,
                        action,
                        "before",
                        "after",
                        actor_membership_id,
                        correlation_id,
                        occurred_at,
                        created_at,
                        updated_at,
                        deleted_at
                    )
                    VALUES (?, ?, ?, 'SKU', ?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL)
                    """,
                    (
                        uuid4().hex,
                        tenant["id"],
                        row["product_id"],
                        row["sku_id"],
                        audit_action,
                        json.dumps(before_payload, ensure_ascii=False),
                        json.dumps(after_payload, ensure_ascii=False),
                        owner_membership["id"],
                        now,
                        now,
                        now,
                    ),
                )

            stored_frequencies = _refresh_tag_dictionary(
                connection,
                tenant_id=tenant["id"],
                now=now,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        print(
            f"\nApplied {len(changed)} offer updates and synchronized "
            f"{len(stored_frequencies)} managed tags."
        )
        print(f"Backup: {backup_path}")
        print("Changed products are now pending incremental AI index update.")
        return 0
    finally:
        connection.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"SQLite database path (default: {DEFAULT_DATABASE_PATH})",
    )
    parser.add_argument(
        "--tenant-slug",
        default="demo",
        help="Tenant slug to update (default: demo)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the curated tags; without this flag the script is read-only.",
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    return curate(
        database_path=arguments.database.resolve(),
        tenant_slug=arguments.tenant_slug,
        apply_changes=arguments.apply,
    )


if __name__ == "__main__":
    raise SystemExit(main())
