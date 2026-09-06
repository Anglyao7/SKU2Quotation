from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text


def migration_module():
    path = Path(__file__).parents[1] / "migrations/versions/20260906_0133_repair_subaccount_storefront_paths.py"
    spec = importlib.util.spec_from_file_location("repair_0133", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repair_missing_addresses_is_idempotent_and_preserves_existing_paths():
    engine = create_engine("sqlite://")
    repair = migration_module()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE tenants (slug TEXT)"))
        connection.execute(text("CREATE TABLE tenant_public_profiles (slug TEXT, legacy_slugs TEXT)"))
        connection.execute(text("CREATE TABLE users (id TEXT, email_normalized TEXT, display_name TEXT)"))
        connection.execute(text("CREATE TABLE memberships (id TEXT, user_id TEXT, login_identifier TEXT, storefront_slug TEXT UNIQUE, account_scope TEXT, status TEXT, deleted_at TEXT, created_at TEXT)"))
        connection.execute(text("INSERT INTO tenants VALUES ('merchant'), ('aaa')"))
        connection.execute(text("INSERT INTO tenant_public_profiles VALUES ('merchant', '[\"aaa-2\"]')"))
        cases = [
            ("old", "old-login", "kept-address", "active", None),
            ("child", "AAA@example.test", None, "active", None),
            ("blank", "blank", "  ", "active", None),
            ("reserved", "login", None, "active", None),
            ("unicode", "你好", None, "active", None),
            ("paused", "paused", None, "suspended", None),
            ("removed", "removed", None, "removed", None),
            ("deleted", "deleted", None, "active", "2026-01-01"),
        ]
        for identifier, login, slug, status, deleted in cases:
            connection.execute(text("INSERT INTO users VALUES (:id, :email, :display)"), {"id": identifier, "email": "contact@example.test", "display": "Display Name"})
            connection.execute(text("INSERT INTO memberships VALUES (:id, :id, :login, :slug, 'CUSTOMER_SUBACCOUNT', :status, :deleted, '2026-01-01')"), {"id": identifier, "login": login, "slug": slug, "status": status, "deleted": deleted})
        assert repair.backfill_missing_paths(connection) == 5
        actual = dict(connection.execute(text("SELECT id, storefront_slug FROM memberships")).all())
        assert actual == {
            "old": "kept-address", "child": "aaa-3", "blank": "blank",
            "reserved": "login-store", "unicode": "你好", "paused": "paused",
            "removed": None, "deleted": None,
        }
        assert repair.backfill_missing_paths(connection) == 0
    engine.dispose()


@pytest.mark.parametrize("fail", [False, True])
def test_postgres_repair_exempts_only_owner_and_restores_force_rls(monkeypatch, fail):
    repair = migration_module()
    forced = {name: True for name in repair._TABLES}
    forced["users"] = False
    previous = dict(forced)
    bind = MagicMock()
    bind.dialect.name = "postgresql"

    def execute(statement, params=None):
        if "relforcerowsecurity" in str(statement):
            value = forced[params["table_name"].split(".")[1]]
            return SimpleNamespace(scalar_one=lambda: value)
        assert "pg_advisory_xact_lock" in str(statement)

    bind.execute.side_effect = execute
    statements = []

    def execute_ddl(statement):
        statements.append(statement)
        name = statement.split('"')[1]
        forced[name] = "NO FORCE" not in statement

    def backfill(connection):
        assert connection is bind
        assert not any(forced.values()), "Table owner must be able to see all old identities"
        if fail:
            raise ValueError("backfill failed")
        return 6

    monkeypatch.setattr(repair.op, "get_bind", lambda: bind)
    monkeypatch.setattr(repair.op, "get_context", lambda: SimpleNamespace(as_sql=False))
    monkeypatch.setattr(repair.op, "execute", execute_ddl)
    monkeypatch.setattr(repair, "backfill_missing_paths", backfill)
    if fail:
        with pytest.raises(ValueError, match="backfill failed"):
            repair.upgrade()
    else:
        repair.upgrade()
    assert forced == previous
    assert len(statements) == 6
    assert all("DISABLE ROW LEVEL SECURITY" not in sql for sql in statements)


def test_public_alias_discovery_uses_identity_reader_not_unbound_business_role(monkeypatch):
    from app.repositories import public_catalog_repository as repository

    tenant_id = uuid4()
    profile = object()
    business = MagicMock()
    business.bind.dialect.name = "postgresql"
    business.scalar.side_effect = [None, profile]
    identity = MagicMock()
    identity.scalar.return_value = tenant_id
    identity.__enter__.return_value = identity
    monkeypatch.setattr(repository, "AuthSessionLocal", lambda: identity)
    assert repository.find_published_profile_by_slug(business, slug=" AAA ") is profile
    statement = identity.scalar.call_args.args[0]
    assert statement.compile().params["storefront_slug_1"] == "aaa"
    sql = str(statement)
    assert "memberships.account_scope" in sql
    assert "memberships.deleted_at IS NULL" in sql
    assert "users.status" in sql and "users.deleted_at IS NULL" in sql
    assert "tenants.status" in sql and "tenants.deleted_at IS NULL" in sql
    assert all("memberships" not in str(call.args[0]) for call in business.scalar.call_args_list)
    assert business.scalar.call_args.args[0].compile().params["tenant_id_1"] == tenant_id


@pytest.mark.parametrize("found", [True, False])
def test_reuse_request_alias_lookup_without_acquiring_second_identity_connection(monkeypatch, found):
    from app.repositories import public_catalog_repository as repository

    tenant_id = uuid4()
    profile = object()
    business = MagicMock()
    business.bind.dialect.name = "postgresql"
    business.info = {"resolved_public_storefront_aliases": {"aaa": tenant_id if found else None}}
    business.scalar.side_effect = [None, profile] if found else [None]
    business.scalars.return_value.all.return_value = []
    second_connection = MagicMock(side_effect=AssertionError("nested identity connection"))
    monkeypatch.setattr(repository, "AuthSessionLocal", second_connection)
    result = repository.find_published_profile_by_slug(business, slug="AAA")
    assert result is (profile if found else None)
    second_connection.assert_not_called()
