"""Independent automatic translation worker. Run with python -m app.workers.catalog_translation."""
import logging
import os
import signal
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID

import psycopg
from sqlalchemy import select, text
from sqlalchemy.orm import defer

from .. import db_models  # noqa: F401: register all ORM metadata without importing app.main
from ..database import AuthSessionLocal, SessionLocal, engine, set_request_context
from ..identity_models import MembershipRow, TenantRow, UserRow
from ..catalog_translation_models import CatalogTranslationJobRow as Job
from ..translation_automation_models import (
    CatalogTranslationAutomationRow as Automation,
    CatalogTranslationAutomationTenantRow as MerchantAutomation,
    CatalogTranslationChangeRow as Change,
)
from ..model_mixins import utcnow
from ..services.catalog_automation import text_source_snapshot
from ..services.auth.dependencies import RequestContext
from ..services.rbac import list_permissions
from ..use_cases import catalog_translations as translations
from ..use_cases.translation_automation import schedule_one

log = logging.getLogger(__name__)
stop = threading.Event()


def tenants():
    if engine.dialect.name == "postgresql":
        url = os.getenv("TENANT_DIRECTORY_DATABASE_URL", "").strip()
        if not url:
            raise RuntimeError("TENANT_DIRECTORY_DATABASE_URL is required by the automatic translation worker")
        with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1), connect_timeout=5) as connection:
            return [UUID(str(row[0])) for row in connection.execute(
                "SELECT id FROM tenants WHERE status = 'active' AND deleted_at IS NULL ORDER BY id")]
    with SessionLocal() as session:
        return list(session.scalars(select(TenantRow.id).where(TenantRow.status == "active")))


def approved_actor(user_id):
    with AuthSessionLocal() as session:
        user = session.get(UserRow, user_id)
        if user is None or user.status != "active" or user.deleted_at is not None:
            return False
        memberships = session.execute(select(MembershipRow.tenant_id, TenantRow.organization_id).join(TenantRow, MembershipRow.tenant_id == TenantRow.id).where(
            MembershipRow.user_id == user_id, MembershipRow.status == "active", MembershipRow.account_scope == "STAFF",
            TenantRow.status == "active", TenantRow.identity_code == "ADMIN")).all()
    for tenant_id, organization_id in memberships:
        with SessionLocal() as session:
            set_request_context(session, tenant_id=tenant_id, organization_id=organization_id, user_id=user_id)
            if "product.edit" in list_permissions(session, tenant_id=tenant_id, user_id=user_id):
                return True
    return False


def context_for(tenant_id, organization_id, user_id):
    return RequestContext(user_id=user_id, membership_id=UUID(int=0), tenant_id=tenant_id,
        organization_id=organization_id, locale="zh-CN", permission_version=1,
        permissions=frozenset({"product.view", "product.edit"}), is_platform_admin=True)


@contextmanager
def leader_lock():
    # Session-level lock lives on a dedicated connection until every running
    # worker has stopped. A restarted API cannot steal or invalidate it.
    if engine.dialect.name == "postgresql":
        with engine.connect() as connection:
            acquired = connection.scalar(text("SELECT pg_try_advisory_lock(8147319060134)"))
            connection.commit()
            if not acquired:
                raise RuntimeError("An automatic translation worker is already running")
            try:
                backend_pid = connection.scalar(text("SELECT pg_backend_pid()"))
                connection.commit()
                def check_leader():
                    if connection.invalidated or connection.scalar(text("SELECT pg_backend_pid()")) != backend_pid:
                        raise RuntimeError("Automatic translation leader connection was lost")
                    connection.commit()
                yield check_leader
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(8147319060134)"))
    else:
        import fcntl
        from pathlib import Path
        database = str(engine.url.database)
        path = Path(database).resolve().with_suffix(".translation-worker.lock")
        with path.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield lambda: None
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def job_lock(job_id):
    # A new leader must not recover a job still owned by the previous process.
    if engine.dialect.name != "postgresql":
        yield True  # SQLite is protected by the process-wide file lock.
        return
    key = job_id.int % (2**63 - 1)
    with engine.connect() as connection:
        acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        connection.commit()
        try:
            yield bool(acquired)
        finally:
            if acquired:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})


def execute_job(**kwargs):
    with job_lock(kwargs["job_id"]) as acquired:
        if acquired:
            translations._run_translation_job(**kwargs)


def ensure_published_language_configs(session, *, tenant_id, merchant, configs):
    """Bring legacy/newly-published languages under the merchant switch.

    Before the switch became merchant-wide, only languages explicitly toggled
    in the console had a runtime row. Provision missing rows lazily in the
    worker and snapshot the current catalog so enabling the new language never
    schedules a historical full translation.
    """
    if merchant is None or not merchant.enabled:
        return []
    published = set(
        translations.translation_repository.available_language_pack_locales(
            session, tenant_id=tenant_id
        )
    )
    if not published:
        return [config for config in configs if config.enabled]
    by_locale = {config.target_locale: config for config in configs}
    actor_id = merchant.updated_by_user_id or next(
        (config.approved_by_user_id for config in configs if config.approved_by_user_id),
        None,
    )
    if actor_id is None:
        return [config for config in configs if config.enabled]
    needs_provision = any(
        locale not in by_locale or not by_locale[locale].enabled
        for locale in published
    )
    if not needs_provision:
        return [config for config in configs if config.enabled]

    rows = translations._status_rows(session, tenant_id=tenant_id)
    snapshot = text_source_snapshot(rows)
    change = session.get(Change, tenant_id)
    generation = change.generation if change else 0
    template = next(iter(configs), None)
    now = utcnow()
    for locale in sorted(published):
        config = by_locale.get(locale)
        was_enabled = bool(config and config.enabled)
        if config is None:
            config = Automation(
                tenant_id=tenant_id,
                target_locale=locale,
                approved_by_user_id=actor_id,
                observed_sources={},
                observed_generation=0,
                updated_at=now,
            )
            session.add(config)
            by_locale[locale] = config
        if not was_enabled:
            config.observed_sources = snapshot
            config.observed_generation = generation
            config.pending_since = None
            config.last_error = None
        config.enabled = True
        config.approved_by_user_id = actor_id
        if template is not None:
            config.auto_publish = template.auto_publish
            config.debounce_seconds = template.debounce_seconds
        config.updated_at = now
    session.commit()
    return [config for config in by_locale.values() if config.enabled]


def run():
    interval = max(2, int(os.getenv("AUTOMATIC_TRANSLATION_POLL_SECONDS", "5")))
    recovered_tenants = set()
    running = {}
    with leader_lock() as check_leader, ThreadPoolExecutor(max_workers=2, thread_name_prefix="automatic-translation") as executor:
        while not stop.is_set():
            check_leader()  # Fail closed rather than reconnect without the lock.
            Path("/tmp/atc-translation-worker.heartbeat").touch()
            running = {key: future for key, future in running.items() if not future.done()}
            approvals = {}
            def is_approved(user_id):
                if user_id not in approvals:
                    approvals[user_id] = approved_actor(user_id)
                return approvals[user_id]
            try:
                for tenant_id in tenants():
                    with SessionLocal() as session:
                        set_request_context(session, tenant_id=tenant_id, organization_id=UUID(int=0), user_id=UUID(int=0))
                        tenant = session.get(TenantRow, tenant_id)
                        if tenant is None:
                            continue
                        organization_id = tenant.organization_id
                        set_request_context(session, tenant_id=tenant_id, organization_id=organization_id, user_id=UUID(int=0))
                        if tenant_id not in recovered_tenants:
                            interrupted = session.scalars(select(Job).where(Job.tenant_id == tenant_id, Job.origin == "AUTOMATIC", Job.status == "RUNNING")).all()
                            for job in interrupted:
                                with job_lock(job.id) as acquired:
                                    if not acquired:
                                        continue
                                    job.status = "PAUSED" if job.pause_requested_at else "QUEUED"
                                    job.stage = job.status
                                    session.commit()
                            session.commit()
                            recovered_tenants.add(tenant_id)
                        merchant_automation = session.get(MerchantAutomation, tenant_id)
                        configs = session.scalars(select(Automation).options(defer(Automation.observed_sources)).where(Automation.tenant_id == tenant_id)).all()
                        configs = ensure_published_language_configs(
                            session,
                            tenant_id=tenant_id,
                            merchant=merchant_automation,
                            configs=configs,
                        )
                        for config in configs:
                            if not is_approved(config.approved_by_user_id):
                                config.enabled = False
                                config.last_error = "开启自动翻译的管理员已停用或不再具备权限，请重新配置。"
                                session.commit()
                                continue
                            actor = context_for(tenant_id, organization_id, config.approved_by_user_id)
                            try:
                                schedule_one(session, context=actor, locale=config.target_locale)
                            except Exception as exc:
                                session.rollback()
                                log.exception("automatic translation scheduling failed for %s/%s", tenant_id, config.target_locale)
                                config.last_error = translations._safe_job_error(exc)
                                config.last_checked_at = utcnow()
                                session.commit()
                        queued = session.scalars(select(Job).where(Job.tenant_id == tenant_id, Job.origin == "AUTOMATIC", Job.status == "QUEUED").order_by(Job.created_at)).all()
                        for job in queued:
                            if stop.is_set() or len(running) >= 2:
                                break
                            if job.id in running:
                                continue
                            if not is_approved(job.requested_by_user_id):
                                job.status = "PAUSED"
                                job.stage = "PAUSED"
                                job.error_message = "自动翻译授权已失效，请管理员检查后继续。"
                                session.commit()
                                continue
                            running[job.id] = executor.submit(execute_job, job_id=job.id,
                                tenant_id=tenant_id, organization_id=organization_id, user_id=job.requested_by_user_id)
            except Exception:
                log.exception("automatic translation worker tick failed")
            stop.wait(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    run()
