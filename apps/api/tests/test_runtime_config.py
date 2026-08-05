from __future__ import annotations

import pytest

from app.runtime_config import (
    cors_origins,
    runtime_metadata,
    startup_configuration_errors,
)
from app.tenant_slugs import RESERVED_TENANT_SLUGS


def _managed_environment(**overrides: str) -> dict[str, str]:
    values = {
        "APP_ENV": "staging",
        "ATC_STRICT_RUNTIME": "true",
        "DATABASE_URL": "postgresql+psycopg://atc_app:secret@postgres/atc",
        "AUTH_DATABASE_URL": "postgresql+psycopg://atc_auth:secret@postgres/atc",
        "AUTO_MIGRATE": "false",
        "SEED_DEMO_DATA": "false",
        "AUTH_TEST_BYPASS": "false",
        "AUTH_PROFILE": "enterprise_oidc",
        "OIDC_ISSUER": "https://identity.example.test/application/o/atc/",
        "OIDC_CLIENT_ID": "atc-web",
        "OIDC_CLIENT_SECRET": "S" * 48,
        "KEYCLOAK_ADMIN_BASE_URL": "http://keycloak:8080",
        "OIDC_REDIRECT_URIS": "https://staging.aitradecloud.example/login/callback",
        "OIDC_SCOPES": "openid profile email",
        "OIDC_ALLOWED_ALGORITHMS": "RS256,ES256",
        "OIDC_TOKEN_ENDPOINT_AUTH_METHOD": "client_secret_basic",
        "OIDC_POST_LOGOUT_REDIRECT_URI": "https://staging.aitradecloud.example/login",
        "PUBLIC_BASE_URL": "https://staging.aitradecloud.example",
        "AUTH_JWT_SECRET": "J" * 48,
        "AUTH_TOKEN_PEPPER": "P" * 48,
        "AUTH_REFRESH_RETRY_GRACE_SECONDS": "5",
        "OBJECT_STORAGE_BACKEND": "s3",
        "OBJECT_STORAGE_BUCKET": "atc-staging-files",
        "FILE_SCANNER_PROFILE": "clamav",
        "CLAMAV_HOST": "clamav.internal",
        "FILE_WORKER_INLINE": "false",
        "OUTBOX_PUBLISHER_PROFILE": "rabbitmq",
        "RABBITMQ_URL": "amqps://rabbitmq.internal/atc",
        "RATE_LIMIT_ENABLED": "true",
        "REDIS_URL": "redis://:strong-redis-password@redis.internal:6379/0",
        "ATC_CORS_ORIGINS": "https://staging.aitradecloud.example",
        "ATC_RELEASE": "r1.2.0-rc.1",
        "ATC_COMMIT_SHA": "a" * 40,
        "ATC_MIGRATION_HEAD": "20260728_0037",
        "ATC_IMAGE_DIGEST": "sha256:" + "b" * 64,
        "ATC_CONFIG_VERSION": "staging-v1",
        "BOOTSTRAP_TENANT_SLUG": "primary",
    }
    values.update(overrides)
    return values


def test_development_runtime_remains_backward_compatible() -> None:
    values = {"APP_ENV": "development"}
    assert startup_configuration_errors(values) == ()
    assert cors_origins(values) == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    assert runtime_metadata(values).mode == "local_persistence"


def test_managed_runtime_accepts_complete_enterprise_oidc_configuration() -> None:
    assert startup_configuration_errors(_managed_environment()) == ()


def test_compact_runtime_keeps_managed_security_and_accepts_local_infrastructure() -> None:
    values = _managed_environment(
        ATC_RUNTIME_PROFILE="compact",
        OBJECT_STORAGE_BACKEND="local",
        OBJECT_STORAGE_BUCKET="",
        FILE_SCANNER_PROFILE="restricted",
        CLAMAV_HOST="",
        FILE_WORKER_INLINE="true",
        TENANT_DIRECTORY_DATABASE_URL=(
            "postgresql+psycopg://atc_scheduler:secret@postgres/atc"
        ),
        OUTBOX_PUBLISHER_PROFILE="inline_database",
        RABBITMQ_URL="",
    )
    assert startup_configuration_errors(values) == ()

    missing_directory = startup_configuration_errors(
        {**values, "TENANT_DIRECTORY_DATABASE_URL": ""}
    )
    assert "TENANT_DIRECTORY_DATABASE_URL_REQUIRED" in missing_directory

    errors = startup_configuration_errors(
        {
            **values,
            "AUTH_PROFILE": "local_fake",
            "DATABASE_URL": "sqlite:///compact.db",
            "AUTH_DATABASE_URL": "sqlite:///compact.db",
            "RATE_LIMIT_ENABLED": "false",
            "ATC_CORS_ORIGINS": "http://localhost:5173",
        }
    )
    assert {
        "DATABASE_URL_POSTGRES_REQUIRED",
        "AUTH_DATABASE_ROLE_SEPARATION_REQUIRED",
        "AUTH_FAKE_PROVIDER_FORBIDDEN",
        "RATE_LIMIT_REQUIRED",
        "CORS_HTTPS_ORIGIN_REQUIRED",
    } <= set(errors)


def test_managed_runtime_rejects_unknown_runtime_profile() -> None:
    errors = startup_configuration_errors(
        _managed_environment(ATC_RUNTIME_PROFILE="tiny-but-undefined")
    )
    assert "RUNTIME_PROFILE_INVALID" in errors


def test_managed_runtime_rejects_fake_adapters_and_placeholder_secrets() -> None:
    errors = startup_configuration_errors(
        _managed_environment(
            AUTH_PROFILE="local_fake",
            AUTH_JWT_SECRET="atc-local-jwt-secret-not-for-staging",
            AUTH_TOKEN_PEPPER="replace-with-at-least-32-random-characters",
            OBJECT_STORAGE_BACKEND="local",
            FILE_SCANNER_PROFILE="development",
            FILE_WORKER_INLINE="true",
            OUTBOX_PUBLISHER_PROFILE="memory",
            ATC_CORS_ORIGINS="http://localhost:5173",
            ATC_IMAGE_DIGEST="unavailable",
        )
    )
    assert {
        "AUTH_FAKE_PROVIDER_FORBIDDEN",
        "AUTH_JWT_SECRET_INVALID",
        "AUTH_TOKEN_PEPPER_INVALID",
        "OBJECT_STORAGE_S3_REQUIRED",
        "CLAMAV_SCANNER_REQUIRED",
        "INLINE_FILE_WORKER_FORBIDDEN",
        "RABBITMQ_OUTBOX_REQUIRED",
        "CORS_HTTPS_ORIGIN_REQUIRED",
        "IMAGE_DIGEST_REQUIRED",
    } <= set(errors)


def test_managed_runtime_requires_separate_identity_database_role() -> None:
    values = _managed_environment()
    values["AUTH_DATABASE_URL"] = values["DATABASE_URL"]
    assert "AUTH_DATABASE_ROLE_SEPARATION_REQUIRED" in startup_configuration_errors(values)


def test_managed_runtime_requires_authenticated_redis_rate_limits() -> None:
    disabled = startup_configuration_errors(
        _managed_environment(RATE_LIMIT_ENABLED="false")
    )
    unsafe_url = startup_configuration_errors(
        _managed_environment(REDIS_URL="redis://redis.internal:6379/0")
    )
    assert "RATE_LIMIT_REQUIRED" in disabled
    assert "RATE_LIMIT_REDIS_URL_INVALID" in unsafe_url


@pytest.mark.parametrize("value", ["0", "11", "not-an-integer"])
def test_managed_runtime_rejects_unsafe_refresh_retry_grace(value: str) -> None:
    errors = startup_configuration_errors(
        _managed_environment(AUTH_REFRESH_RETRY_GRACE_SECONDS=value)
    )
    assert "AUTH_REFRESH_RETRY_GRACE_INVALID" in errors


def test_managed_runtime_rejects_oidc_logout_open_redirect() -> None:
    errors = startup_configuration_errors(
        _managed_environment(
            OIDC_POST_LOGOUT_REDIRECT_URI="https://evil.example/login",
        )
    )
    assert "OIDC_POST_LOGOUT_REDIRECT_URI_INVALID" in errors


@pytest.mark.parametrize(
    "value",
    (
        "",
        "https://auth.example.test",
        "http://keycloak-postgres:5432",
        "http://keycloak:8080/admin",
    ),
)
def test_managed_runtime_requires_isolated_keycloak_admin_endpoint(
    value: str,
) -> None:
    errors = startup_configuration_errors(
        _managed_environment(KEYCLOAK_ADMIN_BASE_URL=value)
    )
    assert "KEYCLOAK_ADMIN_BASE_URL_INVALID" in errors


def test_managed_runtime_rejects_reserved_bootstrap_tenant_slugs() -> None:
    for slug in RESERVED_TENANT_SLUGS:
        errors = startup_configuration_errors(
            _managed_environment(BOOTSTRAP_TENANT_SLUG=slug)
        )
        assert "BOOTSTRAP_TENANT_SLUG_RESERVED" in errors


def test_managed_runtime_rejects_incomplete_or_unsafe_oidc_configuration() -> None:
    errors = startup_configuration_errors(
        _managed_environment(
            OIDC_ISSUER="http://localhost:8080/realms/demo",
            OIDC_CLIENT_ID="",
            OIDC_CLIENT_SECRET="example",
            OIDC_REDIRECT_URIS="http://localhost:5173/login/callback",
            OIDC_SCOPES="openid profile",
            OIDC_ALLOWED_ALGORITHMS="HS256,none",
            OIDC_ALLOWED_ENDPOINT_HOSTS="127.0.0.1",
            OIDC_TOKEN_ENDPOINT_AUTH_METHOD="none",
        )
    )
    assert {
        "OIDC_ISSUER_HTTPS_REQUIRED",
        "OIDC_CLIENT_ID_REQUIRED",
        "OIDC_CLIENT_SECRET_INVALID",
        "OIDC_REDIRECT_URI_HTTPS_REQUIRED",
        "OIDC_SCOPES_INVALID",
        "OIDC_SIGNING_ALGORITHMS_INVALID",
        "OIDC_CLIENT_AUTH_METHOD_INVALID",
        "OIDC_ENDPOINT_HOSTS_INVALID",
    } <= set(errors)
