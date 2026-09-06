from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import db_models  # noqa: F401
from app.database import Base
from app.catalog_translation_models import CatalogTranslationJobRow as Job
from app.translation_automation_models import CatalogTranslationAutomationRow as Automation, CatalogTranslationChangeRow as Change
from app.model_mixins import utcnow
from app.services.catalog_automation import text_source_snapshot, changed_source_ids
from app.services import automatic_catalog_translation as runner, translation_concurrency as concurrency
from app.services.translation import TranslationIdentity, TranslationProviderError
from app.use_cases import translation_automation as automation, catalog_translations as translations
from app.domain.errors import ApplicationError
from test_catalog_language_packages import _catalog_rows


@pytest.fixture
def session(tmp_path):
    # Independent, disposable database: no app.main, real tenant data or API keys.
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


@pytest.fixture
def setup(session, monkeypatch):
    tenant, first, second, rows = _catalog_rows()
    context = SimpleNamespace(tenant_id=tenant, user_id=uuid4(), is_platform_admin=True, permissions={"product.edit"})
    monkeypatch.setattr(translations, "_status_rows", lambda *a, **k: rows)
    monkeypatch.setattr(translations.translation_repository, "language_pack", lambda *a, **k: SimpleNamespace(version=1))
    monkeypatch.setattr(automation, "resolved_catalog_translator", lambda *a, **k: SimpleNamespace(identity=TranslationIdentity("test", "v1")))
    automation.update_settings(session, context=context, locale="en-US", request=automation.AutomationUpdate(enabled=True))
    return context, rows


def signal(session, context, *, now=None):
    now = now or utcnow()
    change = session.get(Change, context.tenant_id)
    if change:
        change.generation += 1
        change.changed_at = now
    else:
        session.add(Change(tenant_id=context.tenant_id, generation=1, changed_at=now))
    session.commit()
    return now


def schedule(session, context, now):
    assert automation.schedule_one(session, context=context, locale="en-US", now=now) is None
    return automation.schedule_one(session, context=context, locale="en-US", now=now + timedelta(seconds=31))


def test_text_fingerprint_ignores_versions_prices_and_images():
    _, first, second, rows = _catalog_rows()
    before = text_source_snapshot(rows)
    rows[0][1].version += 1
    rows[0][2].current_version += 1
    rows[0][0].unit_price = 999
    rows[0][1].image_urls = ["changed.jpg"]
    rows[0][1].updated_at = utcnow()
    assert text_source_snapshot(rows) == before
    rows[0][1].name = "新的红色水杯"
    assert changed_source_ids(before, text_source_snapshot(rows)) == [str(first)]
    rows[0][3].path = "新品/宠物用品"
    assert set(changed_source_ids(before, text_source_snapshot(rows))) == {str(first), str(second)}


def test_enable_creates_baseline_without_historical_retranslation(session, setup):
    context, rows = setup
    assert session.scalars(select(Job)).all() == []
    config = session.get(Automation, (context.tenant_id, "en-US"))
    assert config.observed_sources == text_source_snapshot(rows)
    assert not config.auto_publish
    assert automation.status(session, tenant_id=context.tenant_id, locale="en-US")["state"] == "IDLE"


def test_settings_are_admin_only_and_require_initial_package(session, monkeypatch):
    context = SimpleNamespace(tenant_id=uuid4(), user_id=uuid4(), is_platform_admin=False, permissions={"product.edit"})
    with pytest.raises(ApplicationError):
        automation.update_settings(session, context=context, locale="en-US", request=automation.AutomationUpdate(enabled=True))
    context.is_platform_admin = True
    monkeypatch.setattr(translations.translation_repository, "language_pack", lambda *a, **k: None)
    with pytest.raises(ApplicationError) as caught:
        automation.update_settings(session, context=context, locale="en-US", request=automation.AutomationUpdate(enabled=True))
    assert caught.value.code == "AUTOMATIC_TRANSLATION_PACKAGE_REQUIRED"


def test_price_only_signal_creates_no_job(session, setup):
    context, rows = setup
    rows[0][1].version += 1
    assert schedule(session, context, signal(session, context)) is None
    assert session.scalars(select(Job)).all() == []


def test_coalesces_changes_and_scopes_job_to_changed_sku(session, setup):
    context, rows = setup
    rows[0][1].name = "新名称"
    now = signal(session, context)
    assert automation.schedule_one(session, context=context, locale="en-US", now=now) is None
    signal(session, context, now=now + timedelta(seconds=20))
    assert automation.schedule_one(session, context=context, locale="en-US", now=now + timedelta(seconds=31)) is None
    job_id = automation.schedule_one(session, context=context, locale="en-US", now=now + timedelta(seconds=51))
    job = session.get(Job, job_id)
    assert job.origin == "AUTOMATIC" and job.execution_mode == "REALTIME"
    assert job.total_skus == 1
    assert set(job.automatic_scope["sources"]) == {str(rows[0][1].id)}
    assert automation.status(session, tenant_id=context.tenant_id, locale="en-US")["active_job_id"] == str(job_id)
    assert automation.status(session, tenant_id=context.tenant_id, locale="ja")["state"] == "DISABLED"


@pytest.mark.parametrize("job_status", ["QUEUED", "RUNNING", "PAUSED"])
@pytest.mark.parametrize("origin", ["AUTOMATIC", "MANUAL"])
def test_active_or_paused_job_blocks_auto_without_consuming_change(session, setup, job_status, origin):
    context, rows = setup
    rows[0][1].name = "改名"
    job = Job(tenant_id=context.tenant_id, requested_by_user_id=context.user_id, source_locale="zh-CN", target_locale="en-US", mode="INCREMENTAL", provider="test", provider_version="v1", status=job_status, stage="TRANSLATING" if job_status == "RUNNING" else job_status, origin=origin)
    session.add(job)
    session.commit()
    now = signal(session, context)
    assert schedule(session, context, now) is None
    assert session.get(Automation, (context.tenant_id, "en-US")).observed_generation == 0
    assert job.status == job_status


def test_failed_text_is_not_automatically_retried_but_new_edit_is(session, setup):
    context, rows = setup
    rows[0][1].name = "新名称"
    now = signal(session, context)
    job = session.get(Job, schedule(session, context, now))
    job.status = "FAILED"
    job.stage = "FAILED"
    session.commit()
    assert schedule(session, context, now + timedelta(minutes=20)) is None
    rows[1][1].name = "新增修改"
    later = signal(session, context, now=now + timedelta(minutes=21))
    next_job = session.get(Job, schedule(session, context, later))
    assert set(next_job.automatic_scope["sources"]) == {str(rows[1][1].id)}


def test_provider_failure_rolls_back_baseline(session, setup, monkeypatch):
    context, rows = setup
    rows[0][1].name = "新名称"
    now = signal(session, context)
    automation.schedule_one(session, context=context, locale="en-US", now=now)
    def fail(*a, **k):
        raise TranslationProviderError("upstream unavailable")
    monkeypatch.setattr(automation, "resolved_catalog_translator", fail)
    with pytest.raises(TranslationProviderError):
        automation.schedule_one(session, context=context, locale="en-US", now=now + timedelta(seconds=31))
    session.rollback()
    assert session.get(Automation, (context.tenant_id, "en-US")).observed_generation == 0


def test_run_auto_persists_only_scoped_skus_and_manual_publish_state(session, setup, monkeypatch):
    context, rows = setup
    rows[0][1].name = "新名称"
    job = session.get(Job, schedule(session, context, signal(session, context)))
    translator = SimpleNamespace(identity=TranslationIdentity("test", "v1"))
    monkeypatch.setattr(translations, "resolved_catalog_translator", lambda *a, **k: translator)
    monkeypatch.setattr(translations, "_all_rows", lambda *a, **k: rows)
    monkeypatch.setattr(translations, "_language_pack_override_values", lambda *a, **k: ({}, {}))
    monkeypatch.setattr(translations, "_language_pack_payload", lambda *a, **k: (None, {}))
    monkeypatch.setattr(translations.translation_repository, "translation_map", lambda *a, **k: {})
    def prepare(*a, **k):
        assert [row[1].id for row in k["rows"]] == [rows[0][1].id]
        return False, {}
    monkeypatch.setattr(translations, "_prepare_realtime_translation_values", prepare)
    monkeypatch.setattr(translations, "catalog_translation_result_from_values", lambda *a, **k: object())
    saved = []
    monkeypatch.setattr(translations.translation_repository, "save_translation", lambda *a, **k: saved.append(k["source"].sku_id))
    monkeypatch.setattr(translations, "_pause_at_safe_checkpoint", lambda *a, **k: False)
    runner.run_automatic_job(session, job=job)
    assert saved == [rows[0][1].id]
    assert job.processed_skus == 1 and job.status == "SUCCEEDED"
    assert job.automatic_scope["awaiting_publish"]
    assert not job.package_published
    assert automation.status(session, tenant_id=context.tenant_id, locale="en-US")["state"] == "READY"


def test_global_concurrency_is_shared_between_callers(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    concurrency.configure(2)
    active, peak = 0, 0
    lock = Lock()
    def request():
        nonlocal active, peak
        with concurrency.request_slot(2):
            with lock:
                active += 1
                peak = max(peak, active)
            sleep(0.015)
            with lock:
                active -= 1
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda _: request(), range(20)))
    assert peak == 2 and active == 0


def test_concurrency_redis_failure_is_fail_closed(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://unused")
    monkeypatch.setattr(concurrency, "_client", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(TranslationProviderError, match="Redis"):
        with concurrency.request_slot(2):
            pytest.fail("must not send upstream requests")


def test_publish_builds_from_cache_and_preserves_unrelated_product(session, setup, monkeypatch, tmp_path):
    import copy
    from app.services import catalog_language_packages as packages
    from app.services.language_package_storage import LanguagePackageStorage
    context, rows = setup
    monkeypatch.setenv("TRANSLATION_PACKAGE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("TRANSLATION_PACKAGE_LOCAL_ROOT", str(tmp_path / "packages"))
    storage = LanguagePackageStorage()
    identity = TranslationIdentity("test", "v1")
    def cached_values(**kwargs):
        return {value: f"English text {index}" for index, value in enumerate(kwargs["values"])}
    monkeypatch.setattr(packages, "translate_values_with_memory", cached_values)
    old = packages.build_catalog_language_pack(tenant_id=context.tenant_id, rows=rows, source_locale="zh-CN", target_locale="en-US", version=1, translator=translations._CachedOnlyTranslationProvider(identity), sku_translations={}, previous_payload=None, full_rebuild=False)
    old_sku = copy.deepcopy(old.payload["skus"][str(rows[0][1].id)])
    new_product_rows = _catalog_rows()[3]
    all_rows = rows + new_product_rows
    monkeypatch.setattr(translations, "_all_rows", lambda *a, **k: all_rows)
    monkeypatch.setattr(translations, "_language_pack_payload", lambda *a, **k: (SimpleNamespace(version=1), old.payload))
    monkeypatch.setattr(translations, "_language_pack_override_values", lambda *a, **k: ({}, {}))
    monkeypatch.setattr(translations.translation_repository, "translation_map", lambda *a, **k: {})
    monkeypatch.setattr(translations, "configured_language_package_storage", lambda: storage)
    monkeypatch.setattr(translations.translation_repository, "language_pack", lambda *a, **k: None)
    publication = runner.publish_available_results(session, context=SimpleNamespace(tenant_id=context.tenant_id, locale="en-US"), identity=identity, allowed_ids={str(r[1].id) for r in new_product_rows})
    saved = publication.pack
    import gzip, json
    payload = json.loads(gzip.decompress(storage.get(saved.object_key)))
    assert saved.version == 2
    assert saved.sku_count == 4
    assert payload["skus"][str(rows[0][1].id)] == old_sku
    assert set(payload["products"]) == {str(rows[0][2].id), str(new_product_rows[0][2].id)}


def test_change_triggers_are_transactional_and_watch_bulk_writes(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    path = Path(__file__).parents[1] / "migrations/versions/20260906_0134_automatic_catalog_translation.py"
    spec = importlib.util.spec_from_file_location("automatic_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE tenants(id CHAR(32) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE users(id CHAR(32) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE catalog_translation_jobs(id CHAR(32) PRIMARY KEY)"))
        for table in migration.WATCHED_TABLES:
            connection.execute(text(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY, tenant_id CHAR(32), name TEXT)"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        connection.execute(text("INSERT INTO tenants VALUES ('tenant-a'), ('tenant-b')"))
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO products VALUES (1,'tenant-a','one'), (2,'tenant-a','two'), (3,'tenant-b','three')"))
        assert connection.scalar(text("SELECT generation FROM catalog_translation_changes WHERE tenant_id='tenant-a'")) == 2
        assert connection.scalar(text("SELECT generation FROM catalog_translation_changes WHERE tenant_id='tenant-b'")) == 1
    with engine.connect() as connection:
        connection.execute(text("UPDATE products SET name='changed' WHERE tenant_id='tenant-a'"))
        assert connection.scalar(text("SELECT generation FROM catalog_translation_changes WHERE tenant_id='tenant-a'")) == 4
        connection.rollback()
        assert connection.scalar(text("SELECT generation FROM catalog_translation_changes WHERE tenant_id='tenant-a'")) == 2
        connection.rollback()
        connection.execute(text("DELETE FROM products WHERE tenant_id='tenant-a'"))
        connection.commit()
        assert connection.scalar(text("SELECT generation FROM catalog_translation_changes WHERE tenant_id='tenant-a'")) == 4
    engine.dispose()


def test_postgres_migration_preserves_tenant_rls_and_transaction_triggers(monkeypatch):
    import importlib.util
    from io import StringIO
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / "migrations/versions/20260906_0134_automatic_catalog_translation.py"
    spec = importlib.util.spec_from_file_location("automatic_pg_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    operations = Operations(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}))
    monkeypatch.setattr(migration, "op", operations)
    migration.upgrade()
    sql = output.getvalue()
    assert sql.count("FORCE ROW LEVEL SECURITY") == 2
    assert sql.count("CREATE TRIGGER atc_translation_change") == len(migration.WATCHED_TABLES)
    assert "app.current_tenant_id" in sql
    assert "ON CONFLICT (tenant_id) DO UPDATE" in sql
    assert "SECURITY DEFINER" not in sql
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE public.catalog_translation_changes" in sql
    assert "rolname IN ('atc_app', 'atc_worker')" in sql
    assert sql.index("GRANT SELECT, INSERT, UPDATE") < sql.index("CREATE TRIGGER atc_translation_change")


def test_api_restart_leaves_automatic_job_running(session, setup, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    context, _rows = setup
    for origin, locale in [("MANUAL", "ja"), ("AUTOMATIC", "en-US")]:
        session.add(Job(tenant_id=context.tenant_id, requested_by_user_id=context.user_id, source_locale="zh-CN", target_locale=locale, mode="INCREMENTAL", provider="test", provider_version="v1", status="RUNNING", stage="TRANSLATING", origin=origin))
    session.commit()
    monkeypatch.setattr(translations, "SessionLocal", sessionmaker(bind=session.get_bind()))
    monkeypatch.setattr(translations, "_translation_job_tenant_ids", lambda _: [context.tenant_id])
    assert translations.recover_interrupted_translation_jobs() == 1
    session.expire_all()
    jobs = {job.origin: job.status for job in session.scalars(select(Job))}
    assert jobs == {"MANUAL": "PAUSED", "AUTOMATIC": "RUNNING"}


def test_automatic_dispatch_never_uses_api_executor(session, setup, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    context, rows = setup
    rows[0][1].name = "新名称"
    job_id = schedule(session, context, signal(session, context))
    monkeypatch.setattr(translations, "SessionLocal", sessionmaker(bind=session.get_bind()))
    monkeypatch.setattr(translations, "_translation_executor", SimpleNamespace(submit=lambda *a, **k: pytest.fail("API must not execute automatic jobs")))
    translations._dispatch_translation_job(job_id=job_id, tenant_id=context.tenant_id, organization_id=uuid4(), user_id=context.user_id)


def test_status_does_not_load_large_fingerprint_snapshot(session, setup):
    from sqlalchemy import event
    context, _ = setup
    session.expunge_all()
    statements = []
    def capture(_c, _cursor, statement, *_args):
        statements.append(statement)
    event.listen(session.get_bind(), "before_cursor_execute", capture)
    try:
        automation.status(session, tenant_id=context.tenant_id, locale="en-US")
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", capture)
    assert not any("catalog_translation_automation.observed_sources" in statement for statement in statements)
