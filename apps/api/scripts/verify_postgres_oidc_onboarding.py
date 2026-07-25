"""Verify production OIDC invitation onboarding against real PostgreSQL roles."""

from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def verify_postgres_oidc_onboarding() -> dict[str, Any]:
    owner_url = _required("ATC_POSTGRES_OWNER_URL")
    app_url = _required("ATC_POSTGRES_APP_URL")
    auth_url = _required("ATC_POSTGRES_AUTH_URL")
    os.environ.update(
        DATABASE_URL=app_url,
        AUTH_DATABASE_URL=auth_url,
        AUTO_MIGRATE="false",
        SEED_DEMO_DATA="false",
        APP_ENV="test",
        AUTH_PROFILE="enterprise_oidc",
        AUTH_TEST_BYPASS="false",
    )
    os.environ.setdefault("AUTH_JWT_SECRET", "oidc-conformance-jwt-secret-at-least-32-bytes")
    os.environ.setdefault(
        "AUTH_TOKEN_PEPPER", "oidc-conformance-token-pepper-at-least-32-bytes"
    )

    from fastapi.testclient import TestClient

    from app.identity_models import MembershipRow, UserRow
    from app.main import app
    from app.production_bootstrap import bootstrap_production_owner
    from app.services.auth.contracts import IdentityClaim
    from app.services.auth.oidc_provider import OidcIdentityProviderAdapter

    owner_engine = create_engine(owner_url, pool_pre_ping=True)
    auth_engine = create_engine(auth_url, pool_pre_ping=True)
    try:
        with Session(owner_engine) as session:
            bootstrap = bootstrap_production_owner(
                session,
                organization_code="OIDCCONFORMANCE",
                organization_name="OIDC Conformance Organization",
                tenant_slug="oidc-conformance",
                tenant_name="OIDC Conformance Tenant",
                owner_email="oidc-conformance@example.test",
                owner_display_name="OIDC Conformance Owner",
            )

        direct_membership_update = "blocked"
        try:
            with auth_engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE memberships SET status = status "
                        "WHERE id = :membership_id"
                    ),
                    {"membership_id": bootstrap.membership_id},
                )
        except DBAPIError as exc:
            if "permission denied" not in str(exc).lower():
                raise
        else:
            raise AssertionError("identity role can directly update memberships")

        direct_platform_admin_update = "blocked"
        try:
            with auth_engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE users SET is_platform_admin = NOT is_platform_admin "
                        "WHERE id = :user_id"
                    ),
                    {"user_id": bootstrap.user_id},
                )
        except DBAPIError as exc:
            if "permission denied" not in str(exc).lower():
                raise
        else:
            raise AssertionError("identity role can directly change platform-admin state")

        original_exchange = OidcIdentityProviderAdapter.exchange_authorization_code

        def verified_exchange(
            _self: OidcIdentityProviderAdapter,
            **_kwargs: object,
        ) -> IdentityClaim:
            return IdentityClaim(
                provider=f"oidc:{'c' * 32}",
                subject="postgres-oidc-conformance-subject",
                email_normalized="oidc-conformance@example.test",
                email_verified=True,
                display_name="OIDC Conformance Owner",
            )

        OidcIdentityProviderAdapter.exchange_authorization_code = verified_exchange
        try:
            with TestClient(app) as client:
                login = client.post(
                    "/api/v1/auth/login",
                    json={
                        "provider": "enterprise_oidc",
                        "authorization_code": "postgres-conformance-code",
                        "code_verifier": "V" * 64,
                        "redirect_uri": "https://app.example.test/login/callback",
                        "nonce": "N" * 43,
                    },
                )
        finally:
            OidcIdentityProviderAdapter.exchange_authorization_code = original_exchange
        assert login.status_code == 200, login.text

        with Session(owner_engine) as session:
            from app.database import set_request_context

            set_request_context(
                session,
                organization_id=bootstrap.organization_id,
                tenant_id=bootstrap.tenant_id,
                user_id=bootstrap.user_id,
            )
            user = session.get(UserRow, bootstrap.user_id)
            membership = session.get(MembershipRow, bootstrap.membership_id)
            assert user is not None and membership is not None
            assert user.identity_provider == f"oidc:{'c' * 32}"
            assert user.status == "active"
            assert membership.status == "active"
        return {
            "status": "passed",
            "bootstrap_rls": "allowed_with_deterministic_trusted_context",
            "identity_direct_membership_update": direct_membership_update,
            "identity_direct_platform_admin_update": direct_platform_admin_update,
            "invitation_binding_function": "allowed",
            "tenant_id": str(bootstrap.tenant_id),
        }
    finally:
        owner_engine.dispose()
        auth_engine.dispose()


def main() -> None:
    print(json.dumps(verify_postgres_oidc_onboarding(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
