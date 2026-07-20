"""Fail-fast runtime configuration and safe release metadata.

Business rules do not belong in environment variables. This module validates
only deployment/security invariants required before a managed environment may
start.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit


MANAGED_ENVIRONMENTS = {"staging", "production", "prod"}
UNSAFE_SECRET_MARKERS = ("change-me", "example", "local", "not-for", "replace-with")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
MIGRATION_PATTERN = re.compile(r"^[0-9]{8}_[0-9]{4}$")


class RuntimeConfigurationError(RuntimeError):
    def __init__(self, error_codes: tuple[str, ...]) -> None:
        self.error_codes = error_codes
        super().__init__(
            "managed runtime configuration is invalid: " + ", ".join(error_codes)
        )


@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    mode: str
    environment: str
    release: str
    commit: str
    migration_head: str
    image_digest: str
    config_version: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _value(values: Mapping[str, str], name: str, default: str = "") -> str:
    return values.get(name, default).strip()


def _is_true(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def _is_explicit_false(value: str) -> bool:
    return value.lower() in {"0", "false", "no", "off"}


def _secret_is_safe(value: str) -> bool:
    lowered = value.lower()
    return len(value) >= 32 and not any(marker in lowered for marker in UNSAFE_SECRET_MARKERS)


def _cors_errors(raw_value: str) -> list[str]:
    origins = [item.strip() for item in raw_value.split(",") if item.strip()]
    if not origins:
        return ["CORS_ORIGINS_REQUIRED"]
    errors: list[str] = []
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            origin == "*"
            or parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            errors.append("CORS_HTTPS_ORIGIN_REQUIRED")
            break
    return errors


def startup_configuration_errors(
    values: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    values = values or os.environ
    environment = _value(values, "APP_ENV", "development").lower()
    strict = environment in MANAGED_ENVIRONMENTS or _is_true(
        _value(values, "ATC_STRICT_RUNTIME", "false")
    )
    if not strict:
        return ()

    errors: list[str] = []
    database_url = _value(values, "DATABASE_URL")
    auth_database_url = _value(values, "AUTH_DATABASE_URL")
    if not database_url.startswith("postgresql+psycopg://"):
        errors.append("DATABASE_URL_POSTGRES_REQUIRED")
    if (
        not auth_database_url.startswith("postgresql+psycopg://")
        or auth_database_url == database_url
    ):
        errors.append("AUTH_DATABASE_ROLE_SEPARATION_REQUIRED")
    if not _is_explicit_false(_value(values, "AUTO_MIGRATE")):
        errors.append("AUTO_MIGRATE_MUST_BE_FALSE")
    if not _is_explicit_false(_value(values, "SEED_DEMO_DATA")):
        errors.append("SEED_DEMO_DATA_MUST_BE_FALSE")
    if _is_true(_value(values, "AUTH_TEST_BYPASS", "false")):
        errors.append("AUTH_TEST_BYPASS_FORBIDDEN")

    # Only the fake provider is currently implemented. A managed environment
    # must remain fail-closed until an approved OIDC adapter is registered.
    auth_profile = _value(values, "AUTH_PROFILE", "local_fake").lower()
    if auth_profile == "local_fake":
        errors.append("AUTH_FAKE_PROVIDER_FORBIDDEN")
    else:
        errors.append("AUTH_PROVIDER_IMPLEMENTATION_NOT_REGISTERED")

    if not _secret_is_safe(_value(values, "AUTH_JWT_SECRET")):
        errors.append("AUTH_JWT_SECRET_INVALID")
    if not _secret_is_safe(_value(values, "AUTH_TOKEN_PEPPER")):
        errors.append("AUTH_TOKEN_PEPPER_INVALID")

    if _value(values, "OBJECT_STORAGE_BACKEND").lower() != "s3":
        errors.append("OBJECT_STORAGE_S3_REQUIRED")
    if not _value(values, "OBJECT_STORAGE_BUCKET"):
        errors.append("OBJECT_STORAGE_BUCKET_REQUIRED")
    if _value(values, "FILE_SCANNER_PROFILE").lower() != "clamav":
        errors.append("CLAMAV_SCANNER_REQUIRED")
    if not _value(values, "CLAMAV_HOST"):
        errors.append("CLAMAV_HOST_REQUIRED")
    if not _is_explicit_false(_value(values, "FILE_WORKER_INLINE")):
        errors.append("INLINE_FILE_WORKER_FORBIDDEN")
    if _value(values, "OUTBOX_PUBLISHER_PROFILE").lower() != "rabbitmq":
        errors.append("RABBITMQ_OUTBOX_REQUIRED")
    if not _value(values, "RABBITMQ_URL").startswith(("amqp://", "amqps://")):
        errors.append("RABBITMQ_URL_REQUIRED")

    errors.extend(_cors_errors(_value(values, "ATC_CORS_ORIGINS")))

    release = _value(values, "ATC_RELEASE")
    if not release or release.lower() in {"local", "unknown", "latest"}:
        errors.append("RELEASE_VERSION_REQUIRED")
    if not COMMIT_PATTERN.fullmatch(_value(values, "ATC_COMMIT_SHA")):
        errors.append("COMMIT_SHA_REQUIRED")
    if not MIGRATION_PATTERN.fullmatch(_value(values, "ATC_MIGRATION_HEAD")):
        errors.append("MIGRATION_HEAD_REQUIRED")
    if not _value(values, "ATC_IMAGE_DIGEST").startswith("sha256:"):
        errors.append("IMAGE_DIGEST_REQUIRED")
    config_version = _value(values, "ATC_CONFIG_VERSION")
    if not config_version or config_version.lower() in {"local", "unknown", "latest"}:
        errors.append("CONFIG_VERSION_REQUIRED")
    return tuple(dict.fromkeys(errors))


def validate_startup_configuration(
    values: Mapping[str, str] | None = None,
) -> None:
    errors = startup_configuration_errors(values)
    if errors:
        raise RuntimeConfigurationError(errors)


def cors_origins(values: Mapping[str, str] | None = None) -> list[str]:
    values = values or os.environ
    raw_value = _value(values, "ATC_CORS_ORIGINS")
    if raw_value:
        return [item.strip().rstrip("/") for item in raw_value.split(",") if item.strip()]
    return ["http://localhost:5173", "http://127.0.0.1:5173"]


def runtime_metadata(values: Mapping[str, str] | None = None) -> RuntimeMetadata:
    values = values or os.environ
    return RuntimeMetadata(
        mode=_value(values, "ATC_PERSISTENCE_MODE", "local_persistence"),
        environment=_value(values, "APP_ENV", "development"),
        release=_value(values, "ATC_RELEASE", "local"),
        commit=_value(values, "ATC_COMMIT_SHA", "unknown"),
        migration_head=_value(values, "ATC_MIGRATION_HEAD", "unknown"),
        image_digest=_value(values, "ATC_IMAGE_DIGEST", "unavailable"),
        config_version=_value(values, "ATC_CONFIG_VERSION", "local"),
    )
