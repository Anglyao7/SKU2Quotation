from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.catalog_translation_models import CatalogTextTranslationRow
from app.database import API_ROOT
from app.identity_models import TenantRow
from app.services import translation_memory
from app.services.translation import TranslationIdentity
from app.services.translation_memory_patterns import (
    normalized_translation_text,
    numeric_template_hash,
    reuse_numeric_translation,
)
from scripts import backfill_translation_memory_indexes


@pytest.fixture
def memory_database(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Register the referenced UUID type before compiling the isolated table.
    TenantRow.__table__.create(engine)
    CatalogTextTranslationRow.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(translation_memory, "SessionLocal", sessions)
    monkeypatch.setattr(
        translation_memory, "set_public_tenant_context", lambda *_args, **_kw: None
    )
    monkeypatch.delenv("REDIS_URL", raising=False)
    translation_memory._reset_translation_memory_for_tests()
    yield sessions
    translation_memory._reset_translation_memory_for_tests()
    engine.dispose()


def test_normalization_preserves_meaningful_punctuation() -> None:
    assert normalized_translation_text("  猫碗\t 10 cm /  蓝色  ") == "猫碗 10 cm / 蓝色"
    assert normalized_translation_text("猫碗 / 狗碗") != normalized_translation_text(
        "猫碗 狗碗"
    )


def test_numeric_template_reuses_only_safe_literal_changes() -> None:
    assert reuse_numeric_translation(
        old_source="猫碗 10 cm",
        old_translation="Cat bowl 10 cm",
        new_source="猫碗 12 cm",
    ) == "Cat bowl 12 cm"
    assert reuse_numeric_translation(
        old_source="猫碗 10 cm",
        old_translation="Cat bowl 10 cm",
        new_source="狗碗 12 cm",
    ) is None
    assert reuse_numeric_translation(
        old_source="第1代宠物碗",
        old_translation="First-generation pet bowl",
        new_source="第2代宠物碗",
    ) is None
    assert reuse_numeric_translation(
        old_source="猫碗 10 cm",
        old_translation="Cat bowl 10.5 cm",
        new_source="猫碗 12 cm",
    ) is None
    assert numeric_template_hash("型号 A-123，10 cm") is None
    assert numeric_template_hash("猫碗 10 cm") == numeric_template_hash("猫碗 12 cm")
    assert reuse_numeric_translation(
        old_source="猫窝 48×32×32 cm",
        old_translation="Cat bed 48×32×32 cm",
        new_source="猫窝 50×34×34 cm",
    ) == "Cat bed 50×34×34 cm"
    assert reuse_numeric_translation(
        old_source="猫窝 48×32×32 cm",
        old_translation="Cat bed 48×32×32 cm",
        new_source="猫窝 50×34×32 cm",
    ) is None


def test_memory_reuses_spacing_and_number_edits_without_provider(
    memory_database,
) -> None:
    tenant_id = uuid4()
    translation_memory._database_store_many(
        tenant_id=tenant_id,
        source_locale="zh-CN",
        target_locale="en-US",
        provider="qwen",
        provider_version="v1",
        translations={"猫碗  10 cm": "Cat bowl 10 cm"},
    )

    found = translation_memory.cached_translation_values(
        tenant_id=tenant_id,
        values=["猫碗 10 cm", "猫碗 12 cm"],
        source_locale="zh-CN",
        target_locale="en-US",
        provider="another-provider",
        provider_version="v2",
    )

    assert found == {
        "猫碗 10 cm": "Cat bowl 10 cm",
        "猫碗 12 cm": "Cat bowl 12 cm",
    }
    with memory_database() as session:
        derived = session.scalar(
            select(CatalogTextTranslationRow).where(
                CatalogTextTranslationRow.source_text == "猫碗 12 cm"
            )
        )
        assert derived is not None
        assert derived.provider == "tm-numeric-template"
    assert translation_memory.cached_translation_values(
        tenant_id=uuid4(),
        values=["猫碗 12 cm"],
        source_locale="zh-CN",
        target_locale="en-US",
        provider="qwen",
        provider_version="v1",
    ) == {}


def test_old_memory_is_not_deleted_on_new_write(memory_database) -> None:
    tenant_id = uuid4()
    translation_memory._database_store_many(
        tenant_id=tenant_id,
        source_locale="zh-CN",
        target_locale="en-US",
        provider="qwen",
        provider_version="v1",
        translations={"宠物碗": "Pet bowl"},
    )
    with memory_database() as session:
        old = session.scalar(
            select(CatalogTextTranslationRow).where(
                CatalogTextTranslationRow.source_text == "宠物碗"
            )
        )
        assert old is not None
        old.last_accessed_at = datetime.now(UTC) - timedelta(days=365)
        session.commit()
    translation_memory._database_store_many(
        tenant_id=tenant_id,
        source_locale="zh-CN",
        target_locale="en-US",
        provider="qwen",
        provider_version="v1",
        translations={"宠物猫碗": "Cat bowl"},
    )
    assert translation_memory.cached_translation_values(
        tenant_id=tenant_id,
        values=["宠物碗"],
        source_locale="zh-CN",
        target_locale="en-US",
        provider="qwen",
        provider_version="v1",
    ) == {"宠物碗": "Pet bowl"}


def test_existing_memory_can_be_indexed_in_small_batches(
    memory_database, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = uuid4()
    translation_memory._database_store_many(
        tenant_id=tenant_id,
        source_locale="zh-CN",
        target_locale="en-US",
        provider="qwen",
        provider_version="v1",
        translations={"猫碗 10 cm": "Cat bowl 10 cm"},
    )
    with memory_database() as session:
        row = session.scalar(select(CatalogTextTranslationRow))
        assert row is not None
        row.normalized_source_hash = None
        row.numeric_template_hash = None
        session.commit()
    monkeypatch.setattr(backfill_translation_memory_indexes, "SessionLocal", memory_database)
    monkeypatch.setattr(
        backfill_translation_memory_indexes,
        "set_public_tenant_context",
        lambda *_args, **_kw: None,
    )

    assert backfill_translation_memory_indexes.backfill_tenant(
        tenant_id, batch_size=1, pause_seconds=0
    ) == 1
    assert backfill_translation_memory_indexes.backfill_tenant(
        tenant_id, batch_size=1, pause_seconds=0
    ) == 0
    assert translation_memory.cached_translation_values(
        tenant_id=tenant_id,
        values=["猫碗 12 cm"],
        source_locale="zh-CN",
        target_locale="en-US",
        provider="qwen",
        provider_version="v1",
    ) == {"猫碗 12 cm": "Cat bowl 12 cm"}


def test_semantic_edit_still_reaches_qwen(
    memory_database, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = uuid4()
    translation_memory._database_store_many(
        tenant_id=tenant_id,
        source_locale="zh-CN",
        target_locale="en-US",
        provider="qwen",
        provider_version="v1",
        translations={"猫碗 10 cm": "Cat bowl 10 cm"},
    )
    requested: list[str] = []

    def translate(_translator, values, **_kwargs):
        requested.extend(values)
        return ({value: "Dog bowl 12 cm" for value in values}, {})

    monkeypatch.setattr(translation_memory, "_translate_uncached_values", translate)
    translator = type(
        "QwenTranslator",
        (),
        {"identity": TranslationIdentity(provider="qwen", version="v1")},
    )()
    found = translation_memory.translate_values_with_memory(
        tenant_id=tenant_id,
        translator=translator,
        values=["猫碗 12 cm", "狗碗 12 cm"],
        source_locale="zh-CN",
        target_locale="en-US",
    )

    assert found == {
        "猫碗 12 cm": "Cat bowl 12 cm",
        "狗碗 12 cm": "Dog bowl 12 cm",
    }
    assert requested == ["狗碗 12 cm"]


def test_explicit_refresh_bypasses_numeric_template(
    memory_database, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = uuid4()
    translation_memory._database_store_many(
        tenant_id=tenant_id,
        source_locale="zh-CN",
        target_locale="en-US",
        provider="qwen",
        provider_version="v1",
        translations={"猫碗 10 cm": "Cat bowl 10 cm"},
    )
    requested: list[str] = []

    def translate(_translator, values, **_kwargs):
        requested.extend(values)
        return ({value: "Fresh cat bowl 12 cm" for value in values}, {})

    monkeypatch.setattr(translation_memory, "_translate_uncached_values", translate)
    translator = type(
        "QwenTranslator",
        (),
        {"identity": TranslationIdentity(provider="qwen", version="v1")},
    )()
    result = translation_memory.translate_values_with_memory(
        tenant_id=tenant_id,
        translator=translator,
        values=["猫碗 12 cm"],
        source_locale="zh-CN",
        target_locale="en-US",
        force_refresh_values={"猫碗 12 cm"},
    )

    assert result == {"猫碗 12 cm": "Fresh cat bowl 12 cm"}
    assert requested == ["猫碗 12 cm"]


def test_translation_memory_migration_adds_nonblocking_indexes(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'memory-migration.db').as_posix()}"
    configuration = Config(str(API_ROOT / "alembic.ini"))
    configuration.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(configuration, "20260927_0147")
    command.upgrade(configuration, "20260927_0148")

    engine = create_engine(database_url)
    try:
        columns = {
            column["name"]
            for column in inspect(engine).get_columns("catalog_text_translations")
        }
        indexes = {
            index["name"]
            for index in inspect(engine).get_indexes("catalog_text_translations")
        }
        assert {"normalized_source_hash", "numeric_template_hash"} <= columns
        assert {
            "ix_catalog_text_translations_exact_lookup",
            "ix_catalog_text_translations_normalized_lookup",
            "ix_catalog_text_translations_numeric_lookup",
        } <= indexes
    finally:
        engine.dispose()

    command.downgrade(configuration, "20260927_0147")
    engine = create_engine(database_url)
    try:
        columns = {
            column["name"]
            for column in inspect(engine).get_columns("catalog_text_translations")
        }
        assert "normalized_source_hash" not in columns
        assert "numeric_template_hash" not in columns
    finally:
        engine.dispose()
