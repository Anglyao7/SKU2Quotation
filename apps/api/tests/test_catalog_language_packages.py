from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import catalog_language_packages as packages
from app.services.catalog_language_packages import (
    build_catalog_language_pack,
    language_pack_object_key,
)
from app.services.language_package_storage import LanguagePackageStorage
from app.services.translation import TranslationIdentity


class _PackageTranslator:
    identity = TranslationIdentity(provider="package-test", version="v1")

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str:  # pragma: no cover - package builder uses translation memory
        raise AssertionError("language-package values should use translation memory")


def _catalog_rows(*, second_name: str = "蓝色水杯", second_version: int = 1):
    tenant_id = uuid4()
    product_id = uuid4()
    now = datetime(2026, 8, 8, 1, tzinfo=UTC)
    product = SimpleNamespace(
        id=product_id,
        name="宠物饮水杯",
        description="便携可折叠\n适合旅行",
        current_version=1,
        updated_at=now,
    )
    category = SimpleNamespace(
        id=uuid4(),
        name="饮水用品",
        path="宠物用品/饮水用品",
        code="pet-drinking",
        updated_at=now,
    )

    def row(
        *,
        sku_id,
        sku_code: str,
        name: str,
        color: str,
        version: int,
        offset: int,
    ):
        changed_at = now + timedelta(minutes=offset)
        offer = SimpleNamespace(
            tags=["便携", "旅行"],
            display_tag="便携",
            updated_at=changed_at,
        )
        sku = SimpleNamespace(
            id=sku_id,
            sku_code=sku_code,
            name=name,
            version=version,
            option_values={
                "规格名称": "标准款",
                "颜色": color,
                "_sku2quotation": {"variant_option_keys": ["颜色"]},
            },
            updated_at=changed_at,
        )
        return (offer, sku, product, category)

    first_id = uuid4()
    second_id = uuid4()
    return tenant_id, first_id, second_id, [
        row(
            sku_id=first_id,
            sku_code="CUP-RED",
            name="红色水杯",
            color="红色",
            version=1,
            offset=1,
        ),
        row(
            sku_id=second_id,
            sku_code="CUP-BLUE",
            name=second_name,
            color="蓝色",
            version=second_version,
            offset=2 if second_version == 1 else 20,
        ),
    ]


def _translation_stub(calls: list[tuple[str, ...]]):
    def translate_values(**kwargs):
        values = tuple(kwargs["values"])
        calls.append(values)
        return {value: f"EN:{value}" for value in values}

    return translate_values


def test_language_package_builds_complete_versioned_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, first_id, second_id, rows = _catalog_rows()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        packages,
        "translate_values_with_memory",
        _translation_stub(calls),
    )

    build = build_catalog_language_pack(
        tenant_id=tenant_id,
        rows=rows,
        source_locale="zh-CN",
        target_locale="en-US",
        version=1,
        translator=_PackageTranslator(),
        sku_translations={},
        previous_payload=None,
        full_rebuild=True,
    )

    raw = gzip.decompress(build.compressed)
    assert hashlib.sha256(raw).hexdigest() == build.content_sha256
    assert json.loads(raw) == build.payload
    assert build.payload["schema"] == "atc-catalog-language-pack"
    assert build.payload["schema_version"] == 2
    assert build.payload["version"] == 1
    assert build.product_count == 1
    assert build.sku_count == 2
    assert build.category_count == 1
    assert build.payload["skus"][str(first_id)]["name"] == "EN:红色水杯"
    assert build.payload["skus"][str(second_id)]["name"] == "EN:蓝色水杯"
    product = next(iter(build.payload["products"].values()))
    assert product["option_labels"]["颜色"] == "EN:颜色"
    assert product["option_values"]["红色"] == "EN:红色"
    assert calls
    assert language_pack_object_key(
        tenant_id=tenant_id,
        target_locale="en-US",
        version=1,
        content_sha256=build.content_sha256,
    ).endswith(f"catalog-v1-{build.content_sha256[:16]}.json.gz")


def test_incremental_language_package_reuses_unchanged_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, first_id, second_id, initial_rows = _catalog_rows()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        packages,
        "translate_values_with_memory",
        _translation_stub(calls),
    )
    initial = build_catalog_language_pack(
        tenant_id=tenant_id,
        rows=initial_rows,
        source_locale="zh-CN",
        target_locale="en-US",
        version=1,
        translator=_PackageTranslator(),
        sku_translations={},
        previous_payload=None,
        full_rebuild=True,
    )

    _unused, _first, _second, changed_rows = _catalog_rows(
        second_name="深蓝色水杯",
        second_version=2,
    )
    # Keep the same stable identities while simulating a later SKU update.
    changed_rows[0][1].id = first_id
    changed_rows[1][1].id = second_id
    changed_rows[0][2].id = initial_rows[0][2].id
    changed_rows[1][2].id = initial_rows[0][2].id
    calls.clear()
    incremental = build_catalog_language_pack(
        tenant_id=tenant_id,
        rows=changed_rows,
        source_locale="zh-CN",
        target_locale="en-US",
        version=2,
        translator=_PackageTranslator(),
        sku_translations={},
        previous_payload=initial.payload,
        reuse_previous=True,
        full_rebuild=False,
    )

    assert incremental.payload["skus"][str(first_id)] == initial.payload["skus"][str(first_id)]
    assert incremental.payload["skus"][str(second_id)]["name"] == "EN:深蓝色水杯"
    assert incremental.source_cutoff_at > initial.source_cutoff_at
    translated_values = {value for batch in calls for value in batch}
    assert "深蓝色水杯" in translated_values
    assert "红色水杯" not in translated_values
    assert "宠物饮水杯" not in translated_values


def test_incremental_package_detects_specification_changes_without_version_bump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, first_id, second_id, rows = _catalog_rows()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        packages,
        "translate_values_with_memory",
        _translation_stub(calls),
    )
    initial = build_catalog_language_pack(
        tenant_id=tenant_id,
        rows=rows,
        source_locale="zh-CN",
        target_locale="en-US",
        version=1,
        translator=_PackageTranslator(),
        sku_translations={},
        previous_payload=None,
        full_rebuild=True,
    )

    calls.clear()
    rows[1][1].option_values["规格名称"] = "加大款"
    rows[1][1].updated_at += timedelta(hours=1)
    incremental = build_catalog_language_pack(
        tenant_id=tenant_id,
        rows=rows,
        source_locale="zh-CN",
        target_locale="en-US",
        version=2,
        translator=_PackageTranslator(),
        sku_translations={},
        previous_payload=initial.payload,
        reuse_previous=True,
        full_rebuild=False,
    )

    assert incremental.source_digest != initial.source_digest
    assert incremental.payload["skus"][str(first_id)] == initial.payload["skus"][str(first_id)]
    assert incremental.payload["skus"][str(second_id)]["specification"] == "EN:加大款"
    assert any("加大款" in batch for batch in calls)


def test_local_language_package_storage_is_atomic_and_path_safe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("TRANSLATION_PACKAGE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("TRANSLATION_PACKAGE_LOCAL_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "TRANSLATION_PACKAGE_PUBLIC_BASE_URL",
        "https://languages.example.test",
    )
    storage = LanguagePackageStorage()
    content = gzip.compress(b'{"ok":true}', mtime=0)
    stored = storage.put(
        content,
        object_key="translations/tenant/en-US/catalog-v1.json.gz",
    )

    assert storage.status.configured is True
    assert storage.get(stored.object_key) == content
    assert stored.public_url == (
        "https://languages.example.test/translations/tenant/en-US/"
        "catalog-v1.json.gz"
    )
    with pytest.raises(ValueError):
        storage.put(content, object_key="../escape.json.gz")


def test_r2_language_package_storage_configuration_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRANSLATION_PACKAGE_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("TRANSLATION_PACKAGE_BUCKET", "catalog-languages")
    monkeypatch.setenv(
        "TRANSLATION_PACKAGE_ENDPOINT_URL",
        "https://account-id.r2.cloudflarestorage.com",
    )
    monkeypatch.setenv("TRANSLATION_PACKAGE_ACCESS_KEY_ID", "test-access")
    monkeypatch.setenv("TRANSLATION_PACKAGE_SECRET_ACCESS_KEY", "test-secret")

    status = LanguagePackageStorage().status

    assert status.backend == "r2"
    assert status.configured is True
    assert len(status.fingerprint) == 64
