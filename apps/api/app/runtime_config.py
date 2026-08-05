"""Fail-fast runtime configuration and safe release metadata.

Business rules do not belong in environment variables. This module validates
only deployment/security invariants required before a managed environment may
start.
"""

from __future__ import annotations

import os
import re
import ipaddress
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from .tenant_slugs import is_reserved_tenant_slug


MANAGED_ENVIRONMENTS = {"staging", "production", "prod"}
RUNTIME_PROFILES = {"standard", "compact"}
UNSAFE_SECRET_MARKERS = ("change-me", "example", "local", "not-for", "replace-with")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
MIGRATION_PATTERN = re.compile(r"^[0-9]{8}_[0-9]{4}$")
OIDC_SAFE_ALGORITHMS = {
    "RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA",
}


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


def runtime_profile(values: Mapping[str, str] | None = None) -> str:
    """Return the explicit infrastructure profile without weakening auth policy."""

    values = values or os.environ
    return _value(values, "ATC_RUNTIME_PROFILE", "standard").lower()


def inline_database_outbox_enabled(
    values: Mapping[str, str] | None = None,
) -> bool:
    values = values or os.environ
    return (
        runtime_profile(values) == "compact"
        and _value(values, "OUTBOX_PUBLISHER_PROFILE").lower()
        == "inline_database"
    )


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


def _rate_limit_errors(values: Mapping[str, str]) -> list[str]:
    if not _is_true(_value(values, "RATE_LIMIT_ENABLED", "false")):
        return ["RATE_LIMIT_REQUIRED"]
    parsed = urlsplit(_value(values, "REDIS_URL"))
    if (
        parsed.scheme not in {"redis", "rediss"}
        or not parsed.hostname
        or parsed.username not in {None, ""}
        or not parsed.password
    ):
        return ["RATE_LIMIT_REDIS_URL_INVALID"]
    return []


def _refresh_retry_grace_errors(values: Mapping[str, str]) -> list[str]:
    raw_value = _value(values, "AUTH_REFRESH_RETRY_GRACE_SECONDS", "5")
    try:
        seconds = int(raw_value)
    except ValueError:
        return ["AUTH_REFRESH_RETRY_GRACE_INVALID"]
    if seconds < 1 or seconds > 10:
        return ["AUTH_REFRESH_RETRY_GRACE_INVALID"]
    return []


def _oidc_errors(values: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    issuer = _value(values, "OIDC_ISSUER")
    parsed_issuer = urlsplit(issuer)
    try:
        issuer_address = (
            ipaddress.ip_address(parsed_issuer.hostname)
            if parsed_issuer.hostname
            else None
        )
    except ValueError:
        issuer_address = None
    if (
        parsed_issuer.scheme != "https"
        or not parsed_issuer.netloc
        or parsed_issuer.username is not None
        or parsed_issuer.password is not None
        or parsed_issuer.query
        or parsed_issuer.fragment
        or parsed_issuer.hostname in {"localhost", "127.0.0.1", "::1"}
        or (
            issuer_address is not None
            and any(
                (
                    issuer_address.is_private,
                    issuer_address.is_loopback,
                    issuer_address.is_link_local,
                    issuer_address.is_reserved,
                    issuer_address.is_multicast,
                    issuer_address.is_unspecified,
                )
            )
        )
    ):
        errors.append("OIDC_ISSUER_HTTPS_REQUIRED")
    if not _value(values, "OIDC_CLIENT_ID"):
        errors.append("OIDC_CLIENT_ID_REQUIRED")
    method = _value(
        values, "OIDC_TOKEN_ENDPOINT_AUTH_METHOD", "client_secret_basic"
    )
    if method not in {"client_secret_basic", "client_secret_post"}:
        errors.append("OIDC_CLIENT_AUTH_METHOD_INVALID")
    if not _secret_is_safe(_value(values, "OIDC_CLIENT_SECRET")):
        errors.append("OIDC_CLIENT_SECRET_INVALID")
    if _value(values, "KEYCLOAK_ADMIN_BASE_URL") != "http://keycloak:8080":
        errors.append("KEYCLOAK_ADMIN_BASE_URL_INVALID")
    redirect_uris = [
        item.strip()
        for item in _value(values, "OIDC_REDIRECT_URIS").split(",")
        if item.strip()
    ]
    if not redirect_uris:
        errors.append("OIDC_REDIRECT_URIS_REQUIRED")
    elif any(
        (
            (parsed := urlsplit(uri)).scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        for uri in redirect_uris
    ):
        errors.append("OIDC_REDIRECT_URI_HTTPS_REQUIRED")
    scopes = set(_value(values, "OIDC_SCOPES", "openid profile email").split())
    if not {"openid", "email"} <= scopes:
        errors.append("OIDC_SCOPES_INVALID")
    algorithms = {
        item.strip()
        for item in _value(values, "OIDC_ALLOWED_ALGORITHMS", "RS256,ES256").split(",")
        if item.strip()
    }
    if not algorithms or not algorithms <= OIDC_SAFE_ALGORITHMS:
        errors.append("OIDC_SIGNING_ALGORITHMS_INVALID")
    post_logout_redirect = _value(
        values,
        "OIDC_POST_LOGOUT_REDIRECT_URI",
        _value(values, "PUBLIC_BASE_URL").rstrip("/") + "/login",
    )
    public_base = _value(values, "PUBLIC_BASE_URL").rstrip("/")
    expected_post_logout = f"{public_base}/login" if public_base else ""
    parsed_logout = urlsplit(post_logout_redirect)
    if (
        parsed_logout.scheme != "https"
        or not parsed_logout.netloc
        or parsed_logout.username is not None
        or parsed_logout.password is not None
        or parsed_logout.query
        or parsed_logout.fragment
        or parsed_logout.hostname in {"localhost", "127.0.0.1", "::1"}
        or not expected_post_logout
        or post_logout_redirect != expected_post_logout
    ):
        errors.append("OIDC_POST_LOGOUT_REDIRECT_URI_INVALID")
    endpoint_hosts = [
        item.strip().lower()
        for item in _value(values, "OIDC_ALLOWED_ENDPOINT_HOSTS").split(",")
        if item.strip()
    ]
    for hostname in endpoint_hosts:
        invalid = (
            not re.fullmatch(r"[a-z0-9.-]+", hostname)
            or hostname in {"localhost", "localhost.localdomain"}
            or hostname.endswith(".localhost")
        )
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if invalid or (
            address is not None
            and any(
                (
                    address.is_private,
                    address.is_loopback,
                    address.is_link_local,
                    address.is_reserved,
                    address.is_multicast,
                    address.is_unspecified,
                )
            )
        ):
            errors.append("OIDC_ENDPOINT_HOSTS_INVALID")
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
    profile = runtime_profile(values)
    if profile not in RUNTIME_PROFILES:
        errors.append("RUNTIME_PROFILE_INVALID")
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
    bootstrap_tenant_slug = _value(values, "BOOTSTRAP_TENANT_SLUG")
    if bootstrap_tenant_slug and is_reserved_tenant_slug(bootstrap_tenant_slug):
        errors.append("BOOTSTRAP_TENANT_SLUG_RESERVED")

    auth_profile = _value(values, "AUTH_PROFILE", "local_fake").lower()
    if auth_profile == "local_fake":
        errors.append("AUTH_FAKE_PROVIDER_FORBIDDEN")
    elif auth_profile == "enterprise_oidc":
        errors.extend(_oidc_errors(values))
    else:
        errors.append("AUTH_PROVIDER_UNSUPPORTED")

    if not _secret_is_safe(_value(values, "AUTH_JWT_SECRET")):
        errors.append("AUTH_JWT_SECRET_INVALID")
    if not _secret_is_safe(_value(values, "AUTH_TOKEN_PEPPER")):
        errors.append("AUTH_TOKEN_PEPPER_INVALID")
    errors.extend(_refresh_retry_grace_errors(values))

    storage_profile = _value(values, "OBJECT_STORAGE_BACKEND").lower()
    scanner_profile = _value(values, "FILE_SCANNER_PROFILE").lower()
    outbox_profile = _value(values, "OUTBOX_PUBLISHER_PROFILE").lower()
    inline_file_worker = _value(values, "FILE_WORKER_INLINE")
    if profile == "compact":
        if storage_profile not in {"local", "s3"}:
            errors.append("OBJECT_STORAGE_BACKEND_INVALID")
        if storage_profile == "s3" and not _value(values, "OBJECT_STORAGE_BUCKET"):
            errors.append("OBJECT_STORAGE_BUCKET_REQUIRED")
        if scanner_profile not in {"restricted", "clamav"}:
            errors.append("COMPACT_SCANNER_REQUIRED")
        if scanner_profile == "clamav" and not _value(values, "CLAMAV_HOST"):
            errors.append("CLAMAV_HOST_REQUIRED")
        if not (
            _is_true(inline_file_worker)
            or _is_explicit_false(inline_file_worker)
        ):
            errors.append("FILE_WORKER_INLINE_INVALID")
        if _is_true(inline_file_worker):
            tenant_directory_url = _value(
                values,
                "TENANT_DIRECTORY_DATABASE_URL",
            )
            if not tenant_directory_url.startswith("postgresql+psycopg://"):
                errors.append("TENANT_DIRECTORY_DATABASE_URL_REQUIRED")
            elif tenant_directory_url == database_url:
                errors.append("TENANT_DIRECTORY_DATABASE_ROLE_SEPARATION_REQUIRED")
        if outbox_profile not in {"inline_database", "rabbitmq"}:
            errors.append("COMPACT_OUTBOX_REQUIRED")
        if (
            outbox_profile == "rabbitmq"
            and not _value(values, "RABBITMQ_URL").startswith(
                ("amqp://", "amqps://")
            )
        ):
            errors.append("RABBITMQ_URL_REQUIRED")
    else:
        if storage_profile != "s3":
            errors.append("OBJECT_STORAGE_S3_REQUIRED")
        if not _value(values, "OBJECT_STORAGE_BUCKET"):
            errors.append("OBJECT_STORAGE_BUCKET_REQUIRED")
        if scanner_profile != "clamav":
            errors.append("CLAMAV_SCANNER_REQUIRED")
        if not _value(values, "CLAMAV_HOST"):
            errors.append("CLAMAV_HOST_REQUIRED")
        if not _is_explicit_false(inline_file_worker):
            errors.append("INLINE_FILE_WORKER_FORBIDDEN")
        if outbox_profile != "rabbitmq":
            errors.append("RABBITMQ_OUTBOX_REQUIRED")
        if not _value(values, "RABBITMQ_URL").startswith(
            ("amqp://", "amqps://")
        ):
            errors.append("RABBITMQ_URL_REQUIRED")
    errors.extend(_rate_limit_errors(values))

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
