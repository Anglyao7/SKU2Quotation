"""Execute automatic jobs using the existing request history and translation memory."""
import hashlib
import gzip
import json
from dataclasses import dataclass

from ..catalog_translation_models import CatalogLanguagePackRow
from ..model_mixins import utcnow
from ..translation_automation_models import CatalogTranslationAutomationRow
from .catalog_automation import text_source_snapshot
from .translation import TranslationProviderError


@dataclass(frozen=True)
class CachedPublication:
    pack: CatalogLanguagePackRow
    current_sku_ids: frozenset[str]


def publish_available_results(session, *, context, identity, allowed_ids=None):
    """Merge complete cached product groups; never erase the old published package."""
    from ..use_cases import catalog_translations as t

    t._acquire_language_pack_publish_lock(session, tenant_id=context.tenant_id, target_locale=context.locale)
    session.expire_all()
    rows = t._all_rows(session, tenant_id=context.tenant_id)
    current_pack, previous = t._language_pack_payload(session, tenant_id=context.tenant_id, target_locale=context.locale)
    previous = previous or {}
    product_sources, sku_sources = t.catalog_language_pack_source_entries(rows)
    product_hashes = {source["product_id"]: source["source_hash"] for source in product_sources}
    current_product_ids = {source["product_id"] for source in product_sources}
    current_sku_ids = {source["sku_id"] for source in sku_sources}
    products = {key: dict(value) for key, value in previous.get("products", {}).items() if key in current_product_ids}
    skus = {key: dict(value) for key, value in previous.get("skus", {}).items() if key in current_sku_ids}
    groups = {}
    for row in rows:
        groups.setdefault(str(row[2].id), []).append(row)
    overrides, sku_overrides = t._language_pack_override_values(session, tenant_id=context.tenant_id, target_locale=context.locale)
    translated_rows = t.translation_repository.translation_map(session, tenant_id=context.tenant_id,
        sku_ids=[row[1].id for row in rows], target_locale=context.locale)
    next_version = (current_pack.version if current_pack else 0) + 1
    for product_id, group in groups.items():
        if allowed_ids is not None and not any(str(row[1].id) in allowed_ids for row in group):
            continue
        sources, group_skus = t.catalog_language_pack_source_entries(group)
        # An administrator's wording must not silently disappear after source edits.
        if any(override and override.get("source_hash") != source["source_hash"]
               for source, override in [(sources[0], overrides.get(product_id))]
               + [(source, sku_overrides.get(source["sku_id"])) for source in group_skus]):
            continue
        try:
            built = t.build_catalog_language_pack(
                tenant_id=context.tenant_id, rows=group, source_locale="zh-CN", target_locale=context.locale,
                version=next_version, translator=t._CachedOnlyTranslationProvider(identity),
                sku_translations=translated_rows, previous_payload=previous, reuse_previous=True, full_rebuild=False,
                product_overrides=overrides, sku_overrides=sku_overrides,
            )
            payload = json.loads(gzip.decompress(built.compressed))
            products.update(payload["products"])
            skus.update(payload["skus"])
        except TranslationProviderError:
            # Partial progress stays in memory/rows. An incomplete group cannot
            # replace a previously published group or block unrelated products.
            continue
    t.apply_catalog_language_pack_overrides(products=products, skus=skus,
        product_sources=product_sources, sku_sources=sku_sources, product_overrides=overrides, sku_overrides=sku_overrides)
    complete = all(products.get(source["product_id"], {}).get("source_hash") == source["source_hash"] for source in product_sources) and all(
        skus.get(source["sku_id"], {}).get("source_hash") == source["source_hash"] for source in sku_sources)
    digest = t.catalog_rows_source_digest(rows)
    if not complete:
        digest = hashlib.sha256(f"partial:{digest}".encode()).hexdigest()
    categories = {}
    for source in product_sources:
        entry = products.get(source["product_id"])
        if entry and source.get("category"):
            categories[source["category"]] = entry.get("category_label") or source["category"]
    payload = {"schema": t.PACKAGE_SCHEMA, "schema_version": t.PACKAGE_SCHEMA_VERSION,
               "source_locale": "zh-CN", "target_locale": context.locale,
               "products": products, "skus": skus, "categories": categories}
    build = t.repack_catalog_language_pack_payload(payload, version=next_version, source_digest=digest,
        source_cutoff_at=t.catalog_language_pack_source_cutoff(rows))
    storage = t.configured_language_package_storage()
    stored = storage.put(build.compressed, object_key=t.language_pack_object_key(tenant_id=context.tenant_id,
        target_locale=context.locale, version=next_version, content_sha256=build.content_sha256))
    pack = t.translation_repository.save_language_pack(session, tenant_id=context.tenant_id, source_locale="zh-CN",
        target_locale=context.locale, version=next_version, object_key=stored.object_key, public_url=stored.public_url,
        content_sha256=build.content_sha256, source_digest=digest, storage_fingerprint=storage.status.fingerprint,
        byte_size=stored.byte_size, product_count=build.product_count, sku_count=build.sku_count,
        category_count=build.category_count, provider=identity.provider, provider_version=identity.version,
        source_cutoff_at=build.source_cutoff_at, published_at=utcnow(), full_rebuild=False)
    session.commit()
    t._cached_admin_language_pack_payload.cache_clear()
    return CachedPublication(pack=pack, current_sku_ids=frozenset(
        source["sku_id"] for source in sku_sources
        if skus.get(source["sku_id"], {}).get("source_hash") == source["source_hash"]
        and products.get(source["product_id"], {}).get("source_hash") == product_hashes.get(source["product_id"])
    ))


def run_automatic_job(session, *, job):
    from types import SimpleNamespace
    from ..use_cases import catalog_translations as t

    translator = t.resolved_catalog_translator(session, environment_factory=t.configured_catalog_translator)
    job.automatic_scope = {**(job.automatic_scope or {}), "awaiting_publish": True}
    expected = dict((job.automatic_scope or {}).get("sources", {}))
    rows = t._all_rows(session, tenant_id=job.tenant_id)
    snapshot = text_source_snapshot(rows)
    scope_ids = {key for key, value in expected.items() if snapshot.get(key) == value}
    products, skus = t.catalog_language_pack_source_entries(rows)
    product_overrides, sku_overrides = t._language_pack_override_values(session, tenant_id=job.tenant_id, target_locale=job.target_locale)
    manual_product_ids = set(product_overrides)
    manual_sku_ids = set(sku_overrides)
    manual_ids = {source["sku_id"] for source in skus if source["product_id"] in manual_product_ids or source["sku_id"] in manual_sku_ids}
    reviewed_ids = {source["sku_id"] for source in skus
                    if sku_overrides.get(source["sku_id"], {}).get("source_hash") == source["source_hash"]}
    # Leave all administrator-reviewed groups for explicit review after changes.
    work_rows = [row for row in rows if str(row[1].id) in scope_ids - manual_ids]
    sources = [t.catalog_translation_source(row) for row in work_rows]
    existing = t.translation_repository.translation_map(session, tenant_id=job.tenant_id,
        sku_ids=[source.sku_id for source in sources], target_locale=job.target_locale)
    candidates = [source for source in sources if source.sku_id not in existing or existing[source.sku_id].source_hash != source.source_hash]
    job.total_skus = len(expected)
    job.processed_skus = len(sources) - len(candidates)
    job.remaining_sku_ids = [str(source.sku_id) for source in candidates]
    job.stage = "TRANSLATING"
    session.commit()
    pack, previous = t._language_pack_payload(session, tenant_id=job.tenant_id, target_locale=job.target_locale)
    error = None
    try:
        paused, available = t._prepare_realtime_translation_values(session, job=job, translator=translator,
            rows=work_rows, sku_translations=existing, previous_payload=previous, reuse_previous=bool(pack),
            force_refresh_values=set(), candidate_sources=candidates)
        if paused:
            return
    except TranslationProviderError as exc:
        error = t._safe_job_error(exc)
        available, _ = t._batch_translation_availability(tenant_id=job.tenant_id, target_locale=job.target_locale,
            identity=translator.identity, values=t.catalog_language_pack_translatable_values(work_rows),
            seed=t.catalog_language_pack_translation_seed(work_rows, sku_translations=existing,
                previous_payload=previous, reuse_previous=bool(pack)))
    session.expire_all()
    current_rows = t._all_rows(session, tenant_id=job.tenant_id)
    current_snapshot = text_source_snapshot(current_rows)
    current_sources = {str(row[1].id): t.catalog_translation_source(row) for row in current_rows}
    current_product_ids = {str(row[1].id): str(row[2].id) for row in current_rows}
    failures = []
    # Manual edits saved while an upstream request was running always win.
    latest_product_overrides, latest_sku_overrides = t._language_pack_override_values(session, tenant_id=job.tenant_id, target_locale=job.target_locale)
    latest_products, latest_skus = t.catalog_language_pack_source_entries(current_rows)
    reviewed_ids |= {source["sku_id"] for source in latest_skus
                     if latest_sku_overrides.get(source["sku_id"], {}).get("source_hash") == source["source_hash"]}
    completed_ids = {str(source.sku_id) for source in sources if source not in candidates} | (reviewed_ids & scope_ids)
    for source in candidates:
        key = str(source.sku_id)
        if current_snapshot.get(key) != expected.get(key):
            continue  # Newer source edits remain queued for the next run.
        if key in latest_sku_overrides or current_product_ids[key] in latest_product_overrides:
            continue
        try:
            source = current_sources[key]
            result = t.catalog_translation_result_from_values(source, available, source_locale="zh-CN", target_locale=job.target_locale)
            t.translation_repository.save_translation(session, tenant_id=job.tenant_id, source_locale="zh-CN",
                target_locale=job.target_locale, source=source, result=result,
                provider=translator.identity.provider, provider_version=translator.identity.version)
            completed_ids.add(key)
        except TranslationProviderError as exc:
            failures.append(t._failure_detail(source, str(exc)))
    remaining = set(expected) - completed_ids
    job.processed_skus = len(completed_ids)
    job.failed_skus = len(remaining)
    job.remaining_sku_ids = sorted(remaining)
    job.failure_details = failures[:100]
    job.stage = "PACKAGING"
    session.commit()
    if t._pause_at_safe_checkpoint(session, job):
        return
    config = session.get(CatalogTranslationAutomationRow, (job.tenant_id, job.target_locale))
    auto_publish = bool(config and config.auto_publish)
    if auto_publish:
        job.stage = "UPLOADING"
        session.commit()
        publish_ids = {key for key in completed_ids if current_snapshot.get(key) == expected.get(key)}
        publication = publish_available_results(session,
            context=SimpleNamespace(tenant_id=job.tenant_id, locale=job.target_locale),
            identity=translator.identity, allowed_ids=publish_ids)
        published = publication.pack
        unpublished = publish_ids - publication.current_sku_ids
        if unpublished:
            remaining |= unpublished
            error = error or "部分商品仍有缺失字段，已保留原语言包内容；请重试或人工微调后发布。"
            job.failed_skus = len(remaining)
            job.remaining_sku_ids = sorted(remaining)
        job.package_version = published.version
        job.package_byte_size = published.byte_size
        job.package_published = True
        job.source_cutoff_at = published.source_cutoff_at
    job.automatic_scope = {**job.automatic_scope, "awaiting_publish": not auto_publish}
    job.status = "FAILED" if remaining or error else "SUCCEEDED"
    job.stage = "FAILED" if job.status == "FAILED" else "PUBLISHED"
    job.error_message = error or ("人工微调或源文已变化，剩余内容需要人工复核。" if remaining else None)
    job.completed_at = utcnow()
    job.current_sku_name = None
    job.current_sku_id = None
    if config:
        config.last_error = job.error_message
    session.commit()
