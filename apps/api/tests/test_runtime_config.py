from __future__ import annotations

from app.runtime_config import (
    cors_origins,
    runtime_metadata,
    startup_configuration_errors,
)


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
        "AUTH_JWT_SECRET": "J" * 48,
        "AUTH_TOKEN_PEPPER": "P" * 48,
        "OBJECT_STORAGE_BACKEND": "s3",
        "OBJECT_STORAGE_BUCKET": "atc-staging-files",
        "FILE_SCANNER_PROFILE": "clamav",
        "CLAMAV_HOST": "clamav.internal",
        "FILE_WORKER_INLINE": "false",
        "OUTBOX_PUBLISHER_PROFILE": "rabbitmq",
        "RABBITMQ_URL": "amqps://rabbitmq.internal/atc",
        "ATC_CORS_ORIGINS": "https://staging.aitradecloud.example",
        "ATC_RELEASE": "r1.2.0-rc.1",
        "ATC_COMMIT_SHA": "a" * 40,
        "ATC_MIGRATION_HEAD": "20260720_0021",
        "ATC_IMAGE_DIGEST": "sha256:" + "b" * 64,
        "ATC_CONFIG_VERSION": "staging-v1",
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


def test_managed_runtime_remains_closed_until_oidc_adapter_is_registered() -> None:
    assert startup_configuration_errors(_managed_environment()) == (
        "AUTH_PROVIDER_IMPLEMENTATION_NOT_REGISTERED",
    )


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
