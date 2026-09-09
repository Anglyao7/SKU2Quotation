"""Admin settings and durable automatic job scheduling (no provider calls here)."""
from datetime import timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from ..catalog_translation_models import CatalogTranslationJobRow
from ..db_models import ImportJobRow
from ..catalog_translation_schemas import CatalogTargetLocale
from ..domain.errors import ApplicationError
from ..model_mixins import utcnow
from ..services.catalog_automation import changed_source_ids, text_source_snapshot
from ..services.translation_configuration import resolved_catalog_translator
from ..services.translation import configured_catalog_translator
from ..translation_automation_models import (
    CatalogTranslationAutomationRow as Automation,
    CatalogTranslationAutomationTenantRow as MerchantAutomation,
    CatalogTranslationChangeRow as Change,
)
from . import catalog_translations as translations


class AutomationUpdate(BaseModel):
    enabled: bool
    auto_publish: bool = False
    debounce_seconds: int = Field(default=30, ge=5, le=600)


def settings(session: Session, tenant_id: UUID, locale: str, *, lock=False):
    query = select(Automation).options(defer(Automation.observed_sources)).where(Automation.tenant_id == tenant_id, Automation.target_locale == locale)
    if lock:
        query = query.with_for_update()
    return session.scalar(query)


def merchant_settings(session: Session, tenant_id: UUID, *, lock=False):
    query = select(MerchantAutomation).where(MerchantAutomation.tenant_id == tenant_id)
    if lock:
        query = query.with_for_update()
    return session.scalar(query)


def _automation_locales(session: Session, tenant_id: UUID) -> list[str]:
    """Return every published target plus legacy runtime rows for this tenant."""
    published = set(
        translations.translation_repository.available_language_pack_locales(
            session, tenant_id=tenant_id
        )
    )
    existing = set(
        session.scalars(
            select(Automation.target_locale).where(Automation.tenant_id == tenant_id)
        ).all()
    )
    return sorted(published | existing)


def status(session: Session, *, tenant_id: UUID, locale: str) -> dict:
    merchant = merchant_settings(session, tenant_id)
    merchant_enabled = bool(merchant and merchant.enabled)
    config = settings(session, tenant_id, locale)
    change = session.get(Change, tenant_id)
    active = session.execute(select(CatalogTranslationJobRow.id, CatalogTranslationJobRow.status, CatalogTranslationJobRow.origin).where(
        CatalogTranslationJobRow.tenant_id == tenant_id, CatalogTranslationJobRow.target_locale == locale,
        CatalogTranslationJobRow.status.in_(("QUEUED", "RUNNING", "PAUSED")),
    ).order_by(CatalogTranslationJobRow.created_at.desc()).limit(1)).first()
    state = "DISABLED"
    if active is not None:
        state = "PAUSED" if active.status == "PAUSED" else "RUNNING" if active.status == "RUNNING" else "QUEUED"
    elif merchant_enabled and config is not None and config.enabled:
        state = "ATTENTION" if config.last_error else "WAITING" if config.pending_since or (change and change.generation != config.observed_generation) else "IDLE"
        latest = session.execute(select(CatalogTranslationJobRow.status,
            CatalogTranslationJobRow.automatic_scope["awaiting_publish"].as_boolean().label("awaiting_publish"),
        ).where(CatalogTranslationJobRow.tenant_id == tenant_id, CatalogTranslationJobRow.id == config.last_job_id)).first() if config.last_job_id else None
        if latest:
            if latest.status == "FAILED" and state == "IDLE":
                state = "ATTENTION"
            elif state == "IDLE" and latest.awaiting_publish:
                state = "READY"
    return {
        "tenant_id": str(tenant_id), "target_locale": locale,
        # `enabled` remains in the response for old clients, but now reflects
        # the merchant-level switch rather than a per-language toggle.
        "enabled": merchant_enabled,
        "merchant_enabled": merchant_enabled,
        "auto_publish": bool(config and config.auto_publish),
        "debounce_seconds": config.debounce_seconds if config else 30,
        "state": state,
        "active_job_id": str(active.id) if active else None,
        "active_job_origin": active.origin if active else None,
        "last_error": config.last_error if config else None,
        "last_checked_at": config.last_checked_at if config else None,
        "last_job_id": str(config.last_job_id) if config and config.last_job_id else None,
    }


def update_settings(session: Session, *, context, locale: CatalogTargetLocale, request: AutomationUpdate) -> dict:
    translations._require_platform_admin(context)
    translations._require(context.permissions, "product.edit")
    merchant = merchant_settings(session, context.tenant_id, lock=True)
    was_enabled = bool(merchant and merchant.enabled)
    published_locales = set(
        translations.translation_repository.available_language_pack_locales(
            session, tenant_id=context.tenant_id
        )
    )
    # Keep the use case friendly to isolated/unit-test sessions and to older
    # databases where the repository list may be unavailable: the selected
    # locale is still valid when its published pack can be resolved directly.
    selected_pack = translations.translation_repository.language_pack(
        session, tenant_id=context.tenant_id, target_locale=locale
    )
    if selected_pack is not None:
        published_locales.add(locale)
    if request.enabled and not published_locales:
        raise ApplicationError(
            "AUTOMATIC_TRANSLATION_PACKAGE_REQUIRED",
            "请先翻译并发布至少一个初始语言包，再开启商家自动增量维护。",
            kind="conflict",
        )
    if merchant is None:
        merchant = MerchantAutomation(
            tenant_id=context.tenant_id,
            enabled=False,
            updated_by_user_id=context.user_id,
            updated_at=utcnow(),
        )
        session.add(merchant)

    # One merchant switch controls every published language. Existing rows
    # remain the per-language runtime state used for progress and history.
    locales = set(_automation_locales(session, context.tenant_id))
    if selected_pack is not None:
        locales.add(locale)
    baseline = None
    if request.enabled and not was_enabled:
        change = session.get(Change, context.tenant_id)
        baseline = text_source_snapshot(
            translations._status_rows(session, tenant_id=context.tenant_id)
        )
        observed_generation = change.generation if change else 0
    else:
        observed_generation = None
    for target_locale in sorted(locales):
        config = settings(session, context.tenant_id, target_locale, lock=True)
        if config is None:
            config = Automation(
                tenant_id=context.tenant_id,
                target_locale=target_locale,
                approved_by_user_id=context.user_id,
                observed_sources={},
                observed_generation=0,
                updated_at=utcnow(),
            )
            session.add(config)
        if baseline is not None:
            # Establish a baseline, not a full rebuild or a retry of old failures.
            config.observed_generation = observed_generation
            config.observed_sources = baseline
            config.pending_since = None
            config.last_error = None
        config.enabled = request.enabled
        config.auto_publish = request.auto_publish
        config.debounce_seconds = request.debounce_seconds
        config.approved_by_user_id = context.user_id
        config.updated_at = utcnow()
    merchant.enabled = request.enabled
    merchant.updated_by_user_id = context.user_id
    merchant.updated_at = utcnow()
    session.commit()
    return status(session, tenant_id=context.tenant_id, locale=locale)


def schedule_one(session: Session, *, context, locale: str, now=None) -> UUID | None:
    """Caller holds the worker leader lock. Manual starts still share the unique job index."""
    now = now or utcnow()
    merchant = merchant_settings(session, context.tenant_id)
    if merchant is None or not merchant.enabled:
        return None
    config = settings(session, context.tenant_id, locale, lock=True)
    if config is None or not config.enabled:
        return None
    if translations._active_job(session, tenant_id=context.tenant_id, target_locale=locale):
        return None  # In particular, never revive an operator-paused job.
    if config.last_error and config.last_checked_at and translations._as_utc(config.last_checked_at) > now - timedelta(minutes=2):
        return None  # Invalid settings/Redis outages cannot spin a hot retry loop.
    importing = session.scalar(select(ImportJobRow.id).where(
        ImportJobRow.tenant_id == context.tenant_id,
        ImportJobRow.status.in_(("scanning", "parsing")),
        ImportJobRow.updated_at > now - timedelta(hours=2),
    ).limit(1))
    if importing:
        return None
    change = session.get(Change, context.tenant_id)
    generation = change.generation if change else 0
    reconcile_due = config.last_checked_at is None or translations._as_utc(config.last_checked_at) < now - timedelta(minutes=10)
    if generation == config.observed_generation and not reconcile_due:
        return None
    if config.pending_since is None:
        config.pending_since = now
        session.commit()
        return None
    last_change = translations._as_utc(change.changed_at) if change else translations._as_utc(config.pending_since)
    quiet = last_change <= now - timedelta(seconds=config.debounce_seconds)
    max_wait = translations._as_utc(config.pending_since) <= now - timedelta(minutes=5)
    if not quiet and not max_wait:
        return None
    rows = translations._status_rows(session, tenant_id=context.tenant_id)
    snapshot = text_source_snapshot(rows)
    changed = changed_source_ids(config.observed_sources or {}, snapshot)
    removed = set(config.observed_sources or {}) - set(snapshot)
    # Check first, then commit snapshot and the queued job atomically.
    config.observed_sources = snapshot
    config.observed_generation = generation
    config.pending_since = None
    config.last_checked_at = now
    if not changed and not removed:
        session.commit()
        return None
    translator = resolved_catalog_translator(session, environment_factory=configured_catalog_translator)
    job = CatalogTranslationJobRow(
        id=uuid4(), tenant_id=context.tenant_id, requested_by_membership_id=None,
        requested_by_user_id=config.approved_by_user_id, source_locale="zh-CN", target_locale=locale,
        mode="INCREMENTAL", execution_mode="REALTIME", origin="AUTOMATIC", status="QUEUED", stage="QUEUED",
        provider=translator.identity.provider, provider_version=translator.identity.version,
        total_skus=len(changed), processed_skus=0, failed_skus=0,
        remaining_sku_ids=changed,
        automatic_scope={"sources": {key: snapshot[key] for key in changed}, "auto_publish": config.auto_publish},
    )
    session.add(job)
    config.last_job_id = job.id
    config.last_error = None
    try:
        session.commit()
    except IntegrityError:
        # A manual task won the race. Roll back the baseline too so no work is lost.
        session.rollback()
        if translations._active_job(session, tenant_id=context.tenant_id, target_locale=locale):
            return None
        raise
    return job.id
