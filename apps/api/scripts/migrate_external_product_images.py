"""Move one tenant's externally hosted product images into managed storage.

The command is dry-run by default.  A real migration requires ``--apply``, an
exact tenant confirmation, and either an explicit source-host allowlist or the
``--allow-all-public-hosts`` escape hatch.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Iterable
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy import create_engine, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app import db_models as _db_models  # noqa: F401
from app.adapters.object_storage import get_object_storage
from app.database import DEFAULT_DATABASE_URL, set_request_context
from app.identity_models import TenantRow
from app.ports.object_storage import ObjectStoragePort
from app.product_supplier_models import ProductImageRow
from app.services.external_image_migration import (
    ImageFileMetadata,
    ImageMigrationError,
    SourcePolicy,
    build_catalog_object_key,
    download_image,
    ensure_object_uploaded,
    host_matches_patterns,
    redacted_source_url,
    source_hostname,
)


ZERO_UUID = UUID(int=0)
RETRYABLE_CODES = frozenset(
    {
        "SOURCE_TIMEOUT",
        "SOURCE_NETWORK_ERROR",
        "SOURCE_HTTP_408",
        "SOURCE_HTTP_425",
        "SOURCE_HTTP_429",
        "SOURCE_HTTP_500",
        "SOURCE_HTTP_502",
        "SOURCE_HTTP_503",
        "SOURCE_HTTP_504",
    }
)


@dataclass(frozen=True, slots=True)
class TenantIdentity:
    id: UUID
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class ImageSnapshot:
    id: UUID
    tenant_id: UUID
    product_id: UUID
    source_url: str


@dataclass(frozen=True, slots=True)
class PreparedImage:
    snapshot: ImageSnapshot
    metadata: ImageFileMetadata
    object_key: str
    uploaded: bool


def _database_url() -> str:
    return (
        os.getenv("ATC_IMAGE_MIGRATION_DATABASE_URL", "").strip()
        or os.getenv("ATC_BOOTSTRAP_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
        or DEFAULT_DATABASE_URL
    )


def _bind_tenant(session: Session, tenant_id: UUID) -> None:
    set_request_context(
        session,
        organization_id=ZERO_UUID,
        tenant_id=tenant_id,
        user_id=ZERO_UUID,
    )


def _resolve_tenant(
    engine: Engine,
    *,
    tenant_id: str | None,
    tenant_slug: str | None,
) -> TenantIdentity:
    resolved_id: UUID | None = None
    if tenant_id:
        try:
            resolved_id = UUID(tenant_id)
        except ValueError as exc:
            raise SystemExit("--tenant-id must be a UUID") from exc
    elif tenant_slug:
        normalized_slug = tenant_slug.casefold().strip()
        if engine.dialect.name == "postgresql":
            with engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT tenant_id FROM tenant_public_profiles "
                        "WHERE slug = :slug "
                        "AND publication_status = 'PUBLISHED' "
                        "AND deleted_at IS NULL"
                    ),
                    {"slug": normalized_slug},
                ).first()
            if row is not None:
                resolved_id = UUID(str(row[0]))
            else:
                directory_url = os.getenv(
                    "ATC_IMAGE_MIGRATION_DIRECTORY_DATABASE_URL",
                    os.getenv("TENANT_DIRECTORY_DATABASE_URL", ""),
                ).strip()
                if directory_url:
                    directory_engine = create_engine(
                        directory_url, pool_pre_ping=True
                    )
                    try:
                        with directory_engine.connect() as connection:
                            row = connection.execute(
                                text(
                                    "SELECT id FROM tenants "
                                    "WHERE slug = :slug AND deleted_at IS NULL"
                                ),
                                {"slug": normalized_slug},
                            ).first()
                    finally:
                        directory_engine.dispose()
                    if row is not None:
                        resolved_id = UUID(str(row[0]))
        else:
            with Session(engine) as session:
                tenant = session.scalar(
                    select(TenantRow).where(
                        TenantRow.slug == normalized_slug,
                        TenantRow.deleted_at.is_(None),
                    )
                )
                if tenant is not None:
                    resolved_id = tenant.id
        if resolved_id is None:
            raise SystemExit(
                "Tenant slug was not visible. Use --tenant-id, publish the "
                "storefront, or configure "
                "ATC_IMAGE_MIGRATION_DIRECTORY_DATABASE_URL."
            )
    if resolved_id is None:
        raise SystemExit("Exactly one of --tenant-id or --tenant-slug is required")

    with Session(engine) as session:
        _bind_tenant(session, resolved_id)
        tenant = session.scalar(
            select(TenantRow).where(
                TenantRow.id == resolved_id,
                TenantRow.deleted_at.is_(None),
            )
        )
        if tenant is None:
            raise SystemExit(f"Tenant not found or inaccessible: {resolved_id}")
        return TenantIdentity(id=tenant.id, slug=tenant.slug, name=tenant.name)


def _load_external_images(
    engine: Engine,
    *,
    tenant_id: UUID,
) -> list[ImageSnapshot]:
    with Session(engine) as session:
        _bind_tenant(session, tenant_id)
        rows = session.scalars(
            select(ProductImageRow)
            .where(
                ProductImageRow.tenant_id == tenant_id,
                ProductImageRow.storage_provider == "EXTERNAL",
                ProductImageRow.deleted_at.is_(None),
                or_(
                    ProductImageRow.object_key.like("https://%"),
                    ProductImageRow.object_key.like("http://%"),
                ),
            )
            .order_by(ProductImageRow.id)
        ).all()
        return [
            ImageSnapshot(
                id=row.id,
                tenant_id=row.tenant_id,
                product_id=row.product_id,
                source_url=row.object_key,
            )
            for row in rows
        ]


def _selected_images(
    images: Iterable[ImageSnapshot],
    *,
    source_hosts: tuple[str, ...],
    limit: int | None,
) -> list[ImageSnapshot]:
    selected: list[ImageSnapshot] = []
    for image in images:
        if source_hosts:
            try:
                hostname = source_hostname(image.source_url)
            except ImageMigrationError:
                continue
            if not host_matches_patterns(hostname, source_hosts):
                continue
        selected.append(image)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def _target_storage_identity() -> tuple[str, str]:
    backend = os.getenv("OBJECT_STORAGE_BACKEND", "local").casefold().strip()
    provider = os.getenv(
        "IMAGE_MIGRATION_TARGET_PROVIDER",
        "S3" if backend == "s3" else "LOCAL",
    ).strip()
    bucket = os.getenv(
        "OBJECT_STORAGE_BUCKET",
        "local-managed-storage" if backend == "local" else "",
    ).strip()
    if not provider or len(provider) > 30:
        raise SystemExit(
            "IMAGE_MIGRATION_TARGET_PROVIDER must contain 1-30 characters"
        )
    if not bucket or len(bucket) > 100:
        raise SystemExit(
            "OBJECT_STORAGE_BUCKET must contain 1-100 characters"
        )
    return provider, bucket


def _prepare_image(
    snapshot: ImageSnapshot,
    *,
    client: httpx.Client,
    policy: SourcePolicy,
    storage: ObjectStoragePort,
    max_bytes: int,
    max_pixels: int,
    max_redirects: int,
    retries: int,
) -> PreparedImage:
    suffix = Path(urlsplit(snapshot.source_url).path).suffix[:12]
    descriptor, raw_path = tempfile.mkstemp(
        prefix="atc-image-migration-", suffix=suffix
    )
    os.close(descriptor)
    path = Path(raw_path)
    try:
        metadata: ImageFileMetadata | None = None
        for attempt in range(retries + 1):
            try:
                metadata = download_image(
                    client,
                    source_url=snapshot.source_url,
                    destination=path,
                    policy=policy,
                    max_bytes=max_bytes,
                    max_pixels=max_pixels,
                    max_redirects=max_redirects,
                )
                break
            except ImageMigrationError as exc:
                if exc.code not in RETRYABLE_CODES or attempt >= retries:
                    raise
                time.sleep(min(4.0, 0.5 * (2**attempt)))
        if metadata is None:  # pragma: no cover - defensive exhaustiveness
            raise ImageMigrationError("SOURCE_RETRY_EXHAUSTED")
        object_key = build_catalog_object_key(
            tenant_id=str(snapshot.tenant_id),
            product_id=str(snapshot.product_id),
            image_id=str(snapshot.id),
            content_sha256=metadata.sha256,
            extension=metadata.extension,
        )
        uploaded = ensure_object_uploaded(
            storage,
            source=path,
            object_key=object_key,
            content_type=metadata.content_type,
            expected_sha256=metadata.sha256,
        )
        return PreparedImage(
            snapshot=snapshot,
            metadata=metadata,
            object_key=object_key,
            uploaded=uploaded,
        )
    finally:
        path.unlink(missing_ok=True)


def _update_image_row(
    engine: Engine,
    *,
    prepared: PreparedImage,
    provider: str,
    bucket: str,
) -> str:
    with Session(engine) as session:
        _bind_tenant(session, prepared.snapshot.tenant_id)
        row = session.scalar(
            select(ProductImageRow).where(
                ProductImageRow.tenant_id == prepared.snapshot.tenant_id,
                ProductImageRow.id == prepared.snapshot.id,
                ProductImageRow.deleted_at.is_(None),
            )
        )
        if row is None:
            return "ROW_MISSING"
        if (
            row.object_key == prepared.object_key
            and row.sha256 == prepared.metadata.sha256
        ):
            return "ALREADY_MIGRATED"
        if (
            row.storage_provider != "EXTERNAL"
            or row.object_key != prepared.snapshot.source_url
        ):
            return "ROW_CHANGED"
        row.storage_provider = provider
        row.bucket = bucket
        row.object_key = prepared.object_key
        row.content_type = prepared.metadata.content_type
        row.byte_size = prepared.metadata.byte_size
        row.sha256 = prepared.metadata.sha256
        row.width = prepared.metadata.width
        row.height = prepared.metadata.height
        session.commit()
        return "MIGRATED"


def _append_state(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    os.chmod(path, 0o600)
    try:
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            stream.write("\n")
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _state_payload(
    *,
    snapshot: ImageSnapshot,
    status: str,
    prepared: PreparedImage | None = None,
    error_code: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "image_id": str(snapshot.id),
        "product_id": str(snapshot.product_id),
        "source_url": redacted_source_url(snapshot.source_url),
        "source_url_sha256": hashlib.sha256(
            snapshot.source_url.encode("utf-8")
        ).hexdigest(),
        "status": status,
    }
    if prepared is not None:
        payload.update(
            {
                "target_object_key": prepared.object_key,
                "content_sha256": prepared.metadata.sha256,
                "byte_size": prepared.metadata.byte_size,
                "content_type": prepared.metadata.content_type,
                "width": prepared.metadata.width,
                "height": prepared.metadata.height,
                "new_upload": prepared.uploaded,
            }
        )
    if error_code:
        payload["error_code"] = error_code
    return payload


def _host_inventory(images: Iterable[ImageSnapshot]) -> tuple[Counter[str], int]:
    hosts: Counter[str] = Counter()
    invalid = 0
    for image in images:
        try:
            hosts[source_hostname(image.source_url)] += 1
        except ImageMigrationError:
            invalid += 1
    return hosts, invalid


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate one tenant's EXTERNAL product images into the currently "
            "configured object storage. Dry-run is the default."
        )
    )
    tenant = parser.add_mutually_exclusive_group(required=True)
    tenant.add_argument("--tenant-id")
    tenant.add_argument("--tenant-slug")
    parser.add_argument(
        "--source-host",
        action="append",
        default=[],
        help=(
            "Exact source hostname or wildcard such as *.example.com. "
            "Repeat for multiple hosts; also limits which rows are selected."
        ),
    )
    parser.add_argument(
        "--allow-all-public-hosts",
        action="store_true",
        help="Allow every public source host. Private/link-local addresses remain blocked.",
    )
    parser.add_argument(
        "--allow-private-source-hosts",
        action="store_true",
        help="Permit private source addresses. Intended only for controlled local testing.",
    )
    parser.add_argument("--limit", type=_positive_int)
    parser.add_argument("--concurrency", type=_positive_int, default=4)
    parser.add_argument("--retries", type=_nonnegative_int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--max-image-mb", type=_positive_int, default=25)
    parser.add_argument("--max-pixels", type=_positive_int, default=100_000_000)
    parser.add_argument("--max-redirects", type=_nonnegative_int, default=5)
    parser.add_argument("--progress-every", type=_positive_int, default=25)
    parser.add_argument(
        "--state-file",
        type=Path,
        help="Append-only JSONL result log; defaults under .runtime/image-migrations/.",
    )
    parser.add_argument(
        "--allow-local-target",
        action="store_true",
        help="Allow applying to local filesystem storage (normally only for tests).",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm-tenant",
        help="Required with --apply; must exactly match the resolved tenant slug or UUID.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be greater than zero")
    if arguments.concurrency > 32:
        raise SystemExit("--concurrency must not exceed 32")

    engine = create_engine(_database_url(), pool_pre_ping=True)
    try:
        tenant = _resolve_tenant(
            engine,
            tenant_id=arguments.tenant_id,
            tenant_slug=arguments.tenant_slug,
        )
        images = _load_external_images(engine, tenant_id=tenant.id)
        hosts, invalid_count = _host_inventory(images)
        selected = _selected_images(
            images,
            source_hosts=tuple(arguments.source_host),
            limit=arguments.limit,
        )

        print(f"Tenant: {tenant.name} ({tenant.slug}, {tenant.id})")
        print(f"External image rows: {len(images)}")
        print("Source hosts:")
        for host, count in hosts.most_common():
            print(f"  {host}: {count}")
        if invalid_count:
            print(f"  <invalid>: {invalid_count}")
        print(f"Selected rows: {len(selected)}")

        if not arguments.apply:
            print(
                "Dry run only. Configure managed object storage, then re-run "
                "with --apply, --confirm-tenant, and an explicit source-host policy."
            )
            return 0

        confirmation = (arguments.confirm_tenant or "").strip()
        if confirmation not in {tenant.slug, str(tenant.id)}:
            raise SystemExit(
                "--confirm-tenant must exactly match the resolved tenant slug or UUID"
            )
        if not arguments.source_host and not arguments.allow_all_public_hosts:
            raise SystemExit(
                "Applying requires at least one --source-host or "
                "--allow-all-public-hosts"
            )
        backend = os.getenv("OBJECT_STORAGE_BACKEND", "local").casefold().strip()
        if backend == "local" and not arguments.allow_local_target:
            raise SystemExit(
                "Target storage is local. Configure OBJECT_STORAGE_BACKEND=s3 "
                "for your own image host, or explicitly use --allow-local-target "
                "for a controlled test."
            )
        if not selected:
            print("Nothing to migrate.")
            return 0

        provider, bucket = _target_storage_identity()
        storage = get_object_storage()
        policy = SourcePolicy(
            allowed_hosts=tuple(arguments.source_host),
            allow_all_public_hosts=arguments.allow_all_public_hosts,
            allow_private_hosts=arguments.allow_private_source_hosts,
        )
        state_file = arguments.state_file or (
            Path(__file__).resolve().parents[3]
            / ".runtime"
            / "image-migrations"
            / f"{tenant.slug}-{tenant.id}.jsonl"
        )
        print(
            f"Target: provider={provider}, bucket={bucket}, "
            f"backend={backend}, state={state_file}"
        )

        migrated = 0
        already_migrated = 0
        failed = 0
        changed = 0
        processed = 0
        limits = httpx.Limits(
            max_connections=max(arguments.concurrency * 2, 8),
            max_keepalive_connections=max(arguments.concurrency, 4),
        )
        timeout = httpx.Timeout(arguments.timeout_seconds)
        with (
            httpx.Client(
                timeout=timeout,
                limits=limits,
                follow_redirects=False,
                trust_env=False,
            ) as client,
            ThreadPoolExecutor(max_workers=arguments.concurrency) as executor,
        ):
            batch_size = max(arguments.concurrency * 4, 8)
            for offset in range(0, len(selected), batch_size):
                batch = selected[offset : offset + batch_size]
                futures: dict[Future[PreparedImage], ImageSnapshot] = {
                    executor.submit(
                        _prepare_image,
                        snapshot,
                        client=client,
                        policy=policy,
                        storage=storage,
                        max_bytes=arguments.max_image_mb * 1024 * 1024,
                        max_pixels=arguments.max_pixels,
                        max_redirects=arguments.max_redirects,
                        retries=arguments.retries,
                    ): snapshot
                    for snapshot in batch
                }
                for future in as_completed(futures):
                    snapshot = futures[future]
                    processed += 1
                    try:
                        prepared = future.result()
                        row_status = _update_image_row(
                            engine,
                            prepared=prepared,
                            provider=provider,
                            bucket=bucket,
                        )
                        if row_status == "MIGRATED":
                            migrated += 1
                        elif row_status == "ALREADY_MIGRATED":
                            already_migrated += 1
                        else:
                            changed += 1
                        _append_state(
                            state_file,
                            _state_payload(
                                snapshot=snapshot,
                                status=row_status,
                                prepared=prepared,
                            ),
                        )
                    except ImageMigrationError as exc:
                        failed += 1
                        _append_state(
                            state_file,
                            _state_payload(
                                snapshot=snapshot,
                                status="FAILED",
                                error_code=exc.code,
                            ),
                        )
                        print(
                            f"[{processed}/{len(selected)}] FAILED "
                            f"image={snapshot.id} source="
                            f"{redacted_source_url(snapshot.source_url)} "
                            f"code={exc.code}"
                        )
                    except Exception as exc:
                        failed += 1
                        error_code = f"UNEXPECTED_{type(exc).__name__.upper()}"
                        _append_state(
                            state_file,
                            _state_payload(
                                snapshot=snapshot,
                                status="FAILED",
                                error_code=error_code,
                            ),
                        )
                        print(
                            f"[{processed}/{len(selected)}] FAILED "
                            f"image={snapshot.id} code={error_code}"
                        )
                    if (
                        processed % arguments.progress_every == 0
                        or processed == len(selected)
                    ):
                        print(
                            f"Progress {processed}/{len(selected)}: "
                            f"migrated={migrated}, existing={already_migrated}, "
                            f"changed={changed}, failed={failed}",
                            flush=True,
                        )
        print(
            "Completed: "
            f"migrated={migrated}, existing={already_migrated}, "
            f"changed={changed}, failed={failed}"
        )
        return 1 if failed else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
