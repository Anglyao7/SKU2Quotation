"""Verify trusted authentication and tenant context on real PostgreSQL roles.

Required environment variables:

* ATC_POSTGRES_OWNER_URL: migration/table owner used only to toggle test state
* ATC_POSTGRES_APP_URL: non-owner, NOBYPASSRLS business application role
* ATC_POSTGRES_AUTH_URL: non-superuser identity role with narrowly granted tables

The script deliberately imports the application only after binding the business
and identity engines to their separate roles.
"""

from __future__ import annotations

import json
import os
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def verify_postgres_auth_context() -> dict[str, Any]:
    owner_url = _required("ATC_POSTGRES_OWNER_URL")
    app_url = _required("ATC_POSTGRES_APP_URL")
    auth_url = _required("ATC_POSTGRES_AUTH_URL")

    os.environ["DATABASE_URL"] = app_url
    os.environ["AUTH_DATABASE_URL"] = auth_url
    os.environ["AUTO_MIGRATE"] = "false"
    os.environ["SEED_DEMO_DATA"] = "false"
    os.environ["APP_ENV"] = "test"
    os.environ["AUTH_PROFILE"] = "local_fake"
    os.environ["AUTH_TEST_BYPASS"] = "false"
    os.environ.setdefault("AUTH_JWT_SECRET", "conformance-jwt-secret-at-least-32-bytes")
    os.environ.setdefault("AUTH_TOKEN_PEPPER", "conformance-token-pepper-at-least-32-bytes")

    from fastapi.testclient import TestClient

    from app.constants import (
        DEFAULT_MEMBERSHIP_ID,
        DEFAULT_ORGANIZATION_ID,
        DEFAULT_OWNER_USER_ID,
        DEFAULT_TENANT_ID,
    )
    from app.main import app

    app_engine = create_engine(app_url, pool_pre_ping=True)
    auth_engine = create_engine(auth_url, pool_pre_ping=True)
    owner_engine = create_engine(owner_url, pool_pre_ping=True)
    try:
        with app_engine.connect() as connection:
            app_role = connection.execute(text("SELECT current_user")).scalar_one()
            app_flags = connection.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            ).one()
        assert not app_flags.rolsuper and not app_flags.rolbypassrls

        with auth_engine.connect() as connection:
            auth_role = connection.execute(text("SELECT current_user")).scalar_one()
            auth_flags = connection.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            ).one()
        assert not auth_flags.rolsuper
        assert auth_flags.rolbypassrls
        try:
            with auth_engine.connect() as connection:
                connection.execute(text("SELECT count(*) FROM ai_tasks"))
        except DBAPIError as exc:
            assert "permission denied" in str(exc).lower()
            auth_reads_business_tables = "blocked"
        else:
            raise AssertionError("identity role can read business tables")

        with TestClient(app) as client:
            assert client.get("/api/v1/suppliers").status_code == 401
            login_response = client.post(
                "/api/v1/auth/login",
                json={
                    "provider": "local_fake",
                    "authorization_code": f"fake:{DEFAULT_OWNER_USER_ID}",
                    "code_verifier": "P" * 43,
                    "redirect_uri": "http://127.0.0.1:5173/login/callback",
                },
            )
            assert login_response.status_code == 200, login_response.text
            login_data = login_response.json()["data"]
            access_token = login_data["access_token"]
            csrf_token = login_data["csrf_token"]
            assert login_data["context"]["tenant_id"] == str(DEFAULT_TENANT_ID)

            me_response = client.get(
                "/api/v1/me",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Tenant-ID": str(uuid4()),
                },
            )
            assert me_response.status_code == 200, me_response.text
            assert me_response.json()["context"]["tenant_id"] == str(DEFAULT_TENANT_ID)

            refresh_response = client.post(
                "/api/v1/auth/refresh",
                headers={"X-CSRF-Token": csrf_token},
            )
            assert refresh_response.status_code == 200, refresh_response.text
            rotated_access = refresh_response.json()["data"]["access_token"]

            with owner_engine.begin() as connection:
                connection.execute(
                    text(
                        "SELECT "
                        "set_config('app.current_organization_id', :organization_id, true), "
                        "set_config('app.current_tenant_id', :tenant_id, true), "
                        "set_config('app.current_user_id', :user_id, true)"
                    ),
                    {
                        "organization_id": str(DEFAULT_ORGANIZATION_ID),
                        "tenant_id": str(DEFAULT_TENANT_ID),
                        "user_id": str(DEFAULT_OWNER_USER_ID),
                    },
                )
                connection.execute(
                    text("UPDATE memberships SET status = 'suspended' WHERE id = :id"),
                    {"id": DEFAULT_MEMBERSHIP_ID},
                )
            suspended = client.get(
                "/api/v1/me",
                headers={"Authorization": f"Bearer {rotated_access}"},
            )
            assert suspended.status_code == 403

            with owner_engine.begin() as connection:
                connection.execute(
                    text(
                        "SELECT "
                        "set_config('app.current_organization_id', :organization_id, true), "
                        "set_config('app.current_tenant_id', :tenant_id, true), "
                        "set_config('app.current_user_id', :user_id, true)"
                    ),
                    {
                        "organization_id": str(DEFAULT_ORGANIZATION_ID),
                        "tenant_id": str(DEFAULT_TENANT_ID),
                        "user_id": str(DEFAULT_OWNER_USER_ID),
                    },
                )
                connection.execute(
                    text("UPDATE memberships SET status = 'active' WHERE id = :id"),
                    {"id": DEFAULT_MEMBERSHIP_ID},
                )

            logout_response = client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {rotated_access}"},
            )
            assert logout_response.status_code == 204
            assert client.get(
                "/api/v1/me",
                headers={"Authorization": f"Bearer {rotated_access}"},
            ).status_code == 401

        return {
            "status": "passed",
            "application_role": app_role,
            "application_role_superuser": bool(app_flags.rolsuper),
            "application_role_bypassrls": bool(app_flags.rolbypassrls),
            "identity_role": auth_role,
            "identity_role_superuser": bool(auth_flags.rolsuper),
            "identity_role_bypassrls": bool(auth_flags.rolbypassrls),
            "identity_role_business_table_access": auth_reads_business_tables,
            "trusted_context": {
                "unauthenticated_business_request": "blocked",
                "signed_access_plus_server_session": "allowed",
                "client_tenant_header": "ignored",
                "suspended_membership": "blocked",
                "refresh_rotation": "passed",
                "logout_revocation": "passed",
            },
        }
    finally:
        app_engine.dispose()
        auth_engine.dispose()
        owner_engine.dispose()


def main() -> None:
    print(json.dumps(verify_postgres_auth_context(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
