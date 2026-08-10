from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.services import query_cache


class _Base(DeclarativeBase):
    pass


class _Product(_Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class _FakePipeline:
    def __init__(self, redis: "_FakeRedis") -> None:
        self.redis = redis
        self.operations: list[tuple[str, str]] = []

    def incr(self, key: str) -> "_FakePipeline":
        self.operations.append(("incr", key))
        return self

    def execute(self) -> list[int]:
        return [self.redis.incr(key) for operation, key in self.operations if operation == "incr"]


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, *, ex: int) -> bool:
        assert ex > 0
        self.values[key] = value
        return True

    def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)

    def incr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    def pipeline(self, *, transaction: bool) -> _FakePipeline:
        assert transaction is False
        return _FakePipeline(self)


def _install_fake(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    url = "redis://:secret@redis:6379/0"
    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.setenv("QUERY_CACHE_ENABLED", "true")
    query_cache._reset_for_tests()
    monkeypatch.setattr(query_cache, "_redis_client", fake)
    monkeypatch.setattr(query_cache, "_redis_client_url", url)
    return fake


def test_query_cache_is_tenant_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch)
    first_tenant = uuid4()
    second_tenant = uuid4()

    first_slot = query_cache.lookup(
        tenant_id=first_tenant,
        domain=query_cache.DOMAIN_CATALOG,
        identity={"kind": "sku-page", "page": 1},
    )
    query_cache.store(first_slot, {"total": 42}, ttl_seconds=30)

    first_hit = query_cache.lookup(
        tenant_id=first_tenant,
        domain=query_cache.DOMAIN_CATALOG,
        identity={"kind": "sku-page", "page": 1},
    )
    second_miss = query_cache.lookup(
        tenant_id=second_tenant,
        domain=query_cache.DOMAIN_CATALOG,
        identity={"kind": "sku-page", "page": 1},
    )

    assert first_hit.hit is True
    assert first_hit.value == {"total": 42}
    assert second_miss.hit is False


def test_generation_invalidation_cannot_publish_stale_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake(monkeypatch)
    tenant_id = uuid4()
    stale_slot = query_cache.lookup(
        tenant_id=tenant_id,
        domain=query_cache.DOMAIN_DASHBOARD,
        identity={"kind": "dashboard"},
    )

    query_cache.invalidate_versions(
        {(tenant_id, query_cache.DOMAIN_DASHBOARD)}
    )
    query_cache.store(stale_slot, {"active_skus": 1}, ttl_seconds=30)

    current = query_cache.lookup(
        tenant_id=tenant_id,
        domain=query_cache.DOMAIN_DASHBOARD,
        identity={"kind": "dashboard"},
    )
    assert current.hit is False


def test_disabled_query_cache_falls_back_without_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    query_cache._reset_for_tests()

    slot = query_cache.lookup(
        tenant_id=uuid4(),
        domain=query_cache.DOMAIN_INVENTORY,
        identity={"kind": "overview"},
    )

    assert slot == query_cache.CacheSlot(key=None)
    query_cache.store(slot, {"ignored": True}, ttl_seconds=20)


def test_unavailable_redis_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch)

    class _UnavailableRedis:
        def get(self, _key: str) -> None:
            raise ConnectionError("redis unavailable")

    monkeypatch.setattr(query_cache, "_redis_client", _UnavailableRedis())

    slot = query_cache.lookup(
        tenant_id=uuid4(),
        domain=query_cache.DOMAIN_DASHBOARD,
        identity={"kind": "dashboard"},
    )

    assert slot == query_cache.CacheSlot(key=None)


def test_commit_publishes_marked_tenant_generations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake(monkeypatch)
    tenant_id = uuid4()

    class _Session:
        info: dict[str, object] = {}

    session = _Session()
    query_cache.mark_tenant_dirty(
        session,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        domains=(query_cache.DOMAIN_CATALOG, query_cache.DOMAIN_DASHBOARD),
    )
    query_cache._publish_invalidations(session)  # type: ignore[arg-type]

    assert fake.get(
        query_cache._generation_key(
            tenant_id=tenant_id,
            domain=query_cache.DOMAIN_CATALOG,
        )
    ) == "1"
    assert fake.get(
        query_cache._generation_key(
            tenant_id=tenant_id,
            domain=query_cache.DOMAIN_DASHBOARD,
        )
    ) == "1"


def test_orm_commit_automatically_invalidates_catalog_domains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake(monkeypatch)
    tenant_id = uuid4()
    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            _Product(
                id=str(uuid4()),
                tenant_id=str(tenant_id),
                name="Cached product",
            )
        )
        session.commit()

    assert fake.get(
        query_cache._generation_key(
            tenant_id=tenant_id,
            domain=query_cache.DOMAIN_CATALOG,
        )
    ) == "1"
    assert fake.get(
        query_cache._generation_key(
            tenant_id=tenant_id,
            domain=query_cache.DOMAIN_INVENTORY,
        )
    ) == "1"
