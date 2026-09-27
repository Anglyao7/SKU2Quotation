"""Populate matching indexes for existing translation memory without downtime.

Run after migration 20260927_0148, once per merchant tenant. The command is
idempotent and commits small batches; interrupted runs may simply be resumed.

    python -m scripts.backfill_translation_memory_indexes TENANT_UUID
"""

from __future__ import annotations

import argparse
from time import sleep
from uuid import UUID

from sqlalchemy import select

from app.catalog_translation_models import CatalogTextTranslationRow
from app.database import SessionLocal, set_public_tenant_context
from app.identity_models import TenantRow  # noqa: F401 - registers the FK target
from app.services.translation_memory_patterns import (
    normalized_translation_hash,
    numeric_template_hash,
)


def backfill_tenant(
    tenant_id: UUID, *, batch_size: int = 500, pause_seconds: float = 0.05
) -> int:
    indexed = 0
    last_id: UUID | None = None
    with SessionLocal() as session:
        set_public_tenant_context(session, tenant_id=tenant_id)
        while True:
            query = select(CatalogTextTranslationRow).where(
                CatalogTextTranslationRow.tenant_id == tenant_id,
                CatalogTextTranslationRow.normalized_source_hash.is_(None),
            )
            if last_id is not None:
                query = query.where(CatalogTextTranslationRow.id > last_id)
            rows = session.scalars(
                query.order_by(CatalogTextTranslationRow.id).limit(batch_size)
            ).all()
            if not rows:
                break
            for row in rows:
                row.normalized_source_hash = normalized_translation_hash(row.source_text)
                row.numeric_template_hash = numeric_template_hash(row.source_text)
            last_id = rows[-1].id
            session.commit()
            indexed += len(rows)
            print(f"Indexed {indexed} translation-memory rows", flush=True)
            if pause_seconds:
                sleep(pause_seconds)
    return indexed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tenant_id", type=UUID)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--pause-ms", type=int, default=50)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 2_000:
        parser.error("--batch-size must be between 1 and 2000")
    if not 0 <= args.pause_ms <= 10_000:
        parser.error("--pause-ms must be between 0 and 10000")
    total = backfill_tenant(
        args.tenant_id,
        batch_size=args.batch_size,
        pause_seconds=args.pause_ms / 1_000,
    )
    print(f"Completed: {total} rows indexed")


if __name__ == "__main__":
    main()
