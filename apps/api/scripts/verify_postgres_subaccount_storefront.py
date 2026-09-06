"""Regression against a DISPOSABLE PostgreSQL database, never production.

Run with ATC_POSTGRES_ISOLATED_TEST=true and ATC_POSTGRES_TEST_URL pointing to
the empty `atc_storefront_regression` database in an isolated test container.
Creates synthetic identities and test-only roles; prints no connection secrets.
"""
from __future__ import annotations

import importlib
import os
from contextlib import contextmanager
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def main() -> None:
    raw_url = os.environ["ATC_POSTGRES_TEST_URL"]
    url = make_url(raw_url)
    assert os.environ.get("ATC_POSTGRES_ISOLATED_TEST") == "true"
    assert url.database == "atc_storefront_regression", "refusing a non-test database"
    assert url.host in {"127.0.0.1", "localhost"}, "test DB must share the isolated local network namespace"
    os.environ["DATABASE_URL"] = raw_url
    os.environ["AUTH_DATABASE_URL"] = raw_url
    os.environ["AUTO_MIGRATE"] = "false"
    from app.database import Base
    from app.identity_models import MembershipRow, MerchantIdentityProfileRow, OrganizationRow, TenantRow, UserRow
    from app.public_catalog_models import TenantPublicProfileRow
    from app.repositories import public_catalog_repository as repository

    migration = importlib.import_module("migrations.versions.20260906_0133_repair_subaccount_storefront_paths")
    engine = create_engine(raw_url)
    org, tenant, member, user = (uuid4() for _ in range(4))
    tables = [model.__table__ for model in (
        OrganizationRow, UserRow, MerchantIdentityProfileRow, TenantRow,
        MembershipRow, TenantPublicProfileRow,
    )]
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")).scalar_one() == 0, "test database must be empty"
        for role, option in (("regression_migration", "NOBYPASSRLS"), ("regression_app", "NOBYPASSRLS"), ("regression_auth", "BYPASSRLS")):
            connection.execute(text(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER {option}"))
        connection.execute(text("GRANT USAGE, CREATE ON SCHEMA public TO regression_migration"))
        connection.execute(text("SET LOCAL ROLE regression_migration"))
        Base.metadata.create_all(connection, tables=tables)
        connection.execute(OrganizationRow.__table__.insert(), {"id": org, "code": "REGRESSION", "name": "Test only"})
        connection.execute(UserRow.__table__.insert(), {"id": user, "display_name": "AAA", "email_normalized": "aaa@example.test", "identity_subject": "regression-child", "status": "active"})
        connection.execute(MerchantIdentityProfileRow.__table__.insert(), {"code": "REGRESSION", "name": "Test only"})
        connection.execute(TenantRow.__table__.insert(), {"id": tenant, "organization_id": org, "slug": "merchant", "name": "Test merchant", "identity_code": "REGRESSION"})
        connection.execute(MembershipRow.__table__.insert(), {"id": member, "tenant_id": tenant, "user_id": user, "account_scope": "CUSTOMER_SUBACCOUNT", "login_identifier": "aaa", "status": "active"})
        connection.execute(TenantPublicProfileRow.__table__.insert(), {"tenant_id": tenant, "slug": "merchant", "publication_status": "PUBLISHED"})
        for name in migration._TABLES:
            connection.execute(text(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY'))
            connection.execute(text(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY'))
            predicate = "publication_status = 'PUBLISHED' AND deleted_at IS NULL" if name == "tenant_public_profiles" else "false"
            connection.execute(text(f'CREATE POLICY regression_visibility ON "{name}" FOR SELECT USING ({predicate})'))
        connection.execute(text("GRANT USAGE ON SCHEMA public TO regression_app, regression_auth"))
        connection.execute(text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO regression_app, regression_auth"))

    for attempt in range(2):
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE regression_migration"))
            assert connection.execute(text("SELECT count(*) FROM memberships")).scalar_one() == 0
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            assert connection.execute(text("SELECT count(*) FROM memberships")).scalar_one() == 0
        with engine.connect() as connection:
            assert connection.execute(text("SELECT storefront_slug FROM memberships WHERE id=:id"), {"id": member}).scalar_one() == "aaa"
            for name in migration._TABLES:
                assert connection.execute(text("SELECT relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:name)"), {"name": name}).scalar_one() is True
    print("PostgreSQL: real NOBYPASSRLS migration owner reproduced the empty backfill; repair and idempotent rerun passed; FORCE RLS restored")

    @contextmanager
    def identity_reader():
        with Session(engine) as session:
            session.execute(text("SET LOCAL ROLE regression_auth"))
            yield session

    original_reader = repository.AuthSessionLocal
    repository.AuthSessionLocal = identity_reader
    try:
        with Session(engine) as business:
            business.execute(text("SET LOCAL ROLE regression_app"))
            assert business.execute(text("SELECT count(*) FROM memberships")).scalar_one() == 0
            profile = repository.find_published_profile_by_slug(business, slug="aaa")
            assert profile is not None and profile.tenant_id == tenant
            assert repository.find_published_profile_by_slug(business, slug="unknown-child") is None
            assert business.execute(text("SELECT count(*) FROM memberships")).scalar_one() == 0
        with engine.begin() as connection:
            connection.execute(text("UPDATE memberships SET status='suspended' WHERE id=:id"), {"id": member})
        with Session(engine) as business:
            business.execute(text("SET LOCAL ROLE regression_app"))
            assert repository.find_published_profile_by_slug(business, slug="aaa") is None
        with engine.begin() as connection:
            connection.execute(text("UPDATE memberships SET status='active' WHERE id=:id"), {"id": member})
            connection.execute(text("UPDATE tenant_public_profiles SET publication_status='SUSPENDED'"))
        with Session(engine) as business:
            business.execute(text("SET LOCAL ROLE regression_app"))
            assert repository.find_published_profile_by_slug(business, slug="aaa") is None
        print("PostgreSQL: anonymous child-path resolution passed; suspended accounts, unknown aliases and unpublished stores rejected; business role still sees zero memberships")
    finally:
        repository.AuthSessionLocal = original_reader
        engine.dispose()


if __name__ == "__main__":
    main()
