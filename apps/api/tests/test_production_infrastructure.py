from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory

from scripts import run_tenant_workers
from scripts.provision_keycloak_user_interactive import _valid_password


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_COMPOSE = REPOSITORY_ROOT / "infra" / "production" / "compose.yaml"
COMPACT_PRODUCTION_COMPOSE = (
    REPOSITORY_ROOT / "infra" / "production" / "compose.compact.yaml"
)


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise AssertionError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _compose() -> dict[str, object]:
    return yaml.load(PRODUCTION_COMPOSE.read_text(encoding="utf-8"), UniqueKeyLoader)


def _compact_compose() -> dict[str, object]:
    return yaml.load(
        COMPACT_PRODUCTION_COMPOSE.read_text(encoding="utf-8"),
        UniqueKeyLoader,
    )


def test_production_release_contract_tracks_the_only_alembic_head() -> None:
    alembic_config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    alembic_config.set_main_option(
        "script_location",
        str(REPOSITORY_ROOT / "apps" / "api" / "migrations"),
    )
    heads = ScriptDirectory.from_config(alembic_config).get_heads()
    assert len(heads) == 1
    head = heads[0]

    compose = _compose()
    assert compose["x-api-build"]["args"]["ATC_MIGRATION_HEAD"] == head
    assert compose["x-api-environment"]["ATC_MIGRATION_HEAD"] == head
    for path in (
        REPOSITORY_ROOT / "apps" / "api" / "Dockerfile",
        REPOSITORY_ROOT / "infra" / "production" / "deploy.sh",
        REPOSITORY_ROOT / "infra" / "local" / "compose.yaml",
        REPOSITORY_ROOT / "docker-compose.yml",
    ):
        assert head in path.read_text(encoding="utf-8"), path


def test_python_image_enforces_current_security_dependency_floors() -> None:
    dockerfile = (
        REPOSITORY_ROOT / "apps" / "api" / "Dockerfile"
    ).read_text(encoding="utf-8")
    requirements = (
        REPOSITORY_ROOT / "apps" / "api" / "requirements.txt"
    ).read_text(encoding="utf-8")
    assert "ARG PIP_VERSION=26.1.2" in dockerfile
    assert 'pip==${PIP_VERSION}' in dockerfile
    assert "cryptography>=48.0.1,<49" in requirements


def test_production_compose_has_one_public_edge_and_private_dependencies() -> None:
    value = _compose()
    services = value["services"]
    assert {
        "caddy",
        "web",
        "api",
        "tenant-worker",
        "product-event-consumer",
        "postgres",
        "redis",
        "rabbitmq",
        "minio",
        "clamav",
        "keycloak",
        "keycloak-postgres",
        "production-bootstrap",
        "keycloak-user-provisioner",
        "keycloak-reconciler",
        "backup-minio",
        "restore-minio",
        "backup-rabbitmq",
        "restore-rabbitmq",
    } <= set(services)

    published = {
        name: service.get("ports", [])
        for name, service in services.items()
        if service.get("ports")
    }
    assert published == {"caddy": ["80:80", "443:443", "443:443/udp"]}
    assert value["networks"]["app"]["internal"] is True
    assert value["networks"]["data"]["internal"] is True
    assert value["networks"]["identity"]["internal"] is True
    assert value["networks"]["identity-admin"]["internal"] is True
    assert value["networks"]["app"]["ipam"]["config"][0]["subnet"] == "172.31.10.0/24"

    caddy = services["caddy"]
    assert "env_file" not in caddy
    assert set(caddy["environment"]) == {"ATC_DOMAIN", "CADDY_ACME_EMAIL"}
    assert set(caddy["networks"]) == {"edge", "app"}
    assert set(services["keycloak"]["networks"]) == {
        "edge",
        "identity",
        "identity-admin",
    }
    assert set(services["api"]["networks"]) == {
        "app",
        "data",
        "identity-admin",
        "egress",
    }
    assert {
        name
        for name, service in services.items()
        if "identity-admin" in service.get("networks", ())
    } == {"api", "keycloak"}
    assert set(services["keycloak-user-provisioner"]["networks"]) == {"identity"}
    assert services["keycloak-user-provisioner"]["entrypoint"] == [
        "python",
        "-m",
        "scripts.provision_keycloak_user_interactive",
    ]
    assert "environment" not in services["keycloak-user-provisioner"]
    assert set(services["keycloak-reconciler"]["networks"]) == {"identity"}
    assert services["keycloak-reconciler"]["entrypoint"] == [
        "python",
        "-m",
        "scripts.reconcile_keycloak_realm",
    ]
    assert "environment" not in services["keycloak-reconciler"]
    assert services["keycloak-reconciler"]["volumes"] == [
        "../../.runtime/keycloak/atc-realm.json:/run/atc/atc-realm.json:ro"
    ]
    assert services["keycloak-reconciler"]["group_add"] == ["0"]
    assert set(services["postgres"]["networks"]) == {"data"}
    assert set(services["keycloak-postgres"]["networks"]) == {"identity"}
    assert services["redis"]["command"][-1] == "noeviction"
    assert services["clamav"]["environment"] == {
        "CLAMD_CONF_StreamMaxLength": "260M",
        "CLAMD_CONF_MaxFileSize": "250M",
        "CLAMD_CONF_MaxScanSize": "500M",
    }


def test_production_workloads_are_pinned_bounded_and_health_checked() -> None:
    services = _compose()["services"]
    long_running = {
        "caddy",
        "web",
        "api",
        "tenant-worker",
        "product-event-consumer",
        "postgres",
        "redis",
        "rabbitmq",
        "minio",
        "clamav",
        "keycloak",
        "keycloak-postgres",
    }
    for name in long_running:
        service = services[name]
        assert not str(service["image"]).endswith(":latest")
        assert service["restart"] == "unless-stopped"
        assert service["logging"]["options"] == {"max-size": "10m", "max-file": "5"}
        assert service["deploy"]["resources"]["limits"]["memory"]
    for name in long_running - {"tenant-worker", "product-event-consumer"}:
        assert "healthcheck" in services[name]

    api_health = " ".join(str(item) for item in services["api"]["healthcheck"]["test"])
    assert "/api/v1/health/ready" in api_health
    assert "--no-access-log" in services["api"]["command"]
    assert "--forwarded-allow-ips=172.31.10.0/24" in services["api"]["command"]


def test_compact_production_keeps_the_secure_core_without_heavy_daemons() -> None:
    value = _compact_compose()
    services = value["services"]
    assert {
        "caddy",
        "web",
        "api",
        "postgres",
        "redis",
        "keycloak",
        "keycloak-postgres",
        "db-bootstrap",
        "db-migrate",
        "db-grants",
        "production-bootstrap",
        "keycloak-reconciler",
        "backup-local-objects",
        "restore-local-objects",
    } <= set(services)
    assert {
        "rabbitmq",
        "minio",
        "clamav",
        "tenant-worker",
        "product-event-consumer",
        "dependency-bootstrap",
    }.isdisjoint(services)

    published = {
        name: service.get("ports", [])
        for name, service in services.items()
        if service.get("ports")
    }
    assert published == {"caddy": ["80:80", "443:443", "443:443/udp"]}
    assert value["networks"]["app"]["internal"] is True
    assert value["networks"]["data"]["internal"] is True
    assert value["networks"]["identity"]["internal"] is True
    assert value["networks"]["identity-admin"]["internal"] is True
    assert value["networks"]["app"]["ipam"]["config"][0]["subnet"] == (
        "172.31.20.0/24"
    )

    environment = services["api"]["environment"]
    assert environment["APP_ENV"] == "production"
    assert environment["ATC_RUNTIME_PROFILE"] == "compact"
    assert environment["OBJECT_STORAGE_BACKEND"] == "${OBJECT_STORAGE_BACKEND:-local}"
    assert environment["OBJECT_STORAGE_BUCKET"] == "${OBJECT_STORAGE_BUCKET:-}"
    assert environment["OBJECT_STORAGE_ENDPOINT_URL"] == (
        "${OBJECT_STORAGE_ENDPOINT_URL:-}"
    )
    assert environment["OBJECT_STORAGE_REGION"] == "${OBJECT_STORAGE_REGION:-auto}"
    assert environment["OBJECT_STORAGE_ACCESS_KEY_ID"] == (
        "${OBJECT_STORAGE_ACCESS_KEY_ID:-}"
    )
    assert environment["OBJECT_STORAGE_SECRET_ACCESS_KEY"] == (
        "${OBJECT_STORAGE_SECRET_ACCESS_KEY:-}"
    )
    assert environment["FILE_SCANNER_PROFILE"] == "restricted"
    assert environment["FILE_WORKER_INLINE"] == "true"
    assert "atc_scheduler:" in environment["TENANT_DIRECTORY_DATABASE_URL"]
    assert environment["OUTBOX_PUBLISHER_PROFILE"] == "inline_database"
    assert environment["AUTH_PROFILE"] == "enterprise_oidc"
    assert environment["OIDC_ISSUER"].startswith("https://auth.")
    assert environment["KEYCLOAK_ADMIN_BASE_URL"] == "http://keycloak:8080"
    assert environment["RATE_LIMIT_ENABLED"] == "true"
    assert set(services["api"]["networks"]) == {
        "app",
        "data",
        "identity-admin",
        "egress",
    }
    assert set(services["keycloak"]["networks"]) == {
        "edge",
        "identity",
        "identity-admin",
    }
    assert {
        name
        for name, service in services.items()
        if "identity-admin" in service.get("networks", ())
    } == {"api", "keycloak"}
    assert services["api"]["volumes"] == [
        "local-object-data:/var/lib/atc/object-storage"
    ]
    assert services["keycloak-reconciler"]["group_add"] == ["0"]
    assert services["web"]["networks"]["app"]["aliases"] == ["atc-frontend"]

    for name in (
        "caddy",
        "web",
        "api",
        "postgres",
        "redis",
        "keycloak",
        "keycloak-postgres",
    ):
        assert services[name]["deploy"]["resources"]["limits"]["memory"]
        assert not str(services[name]["image"]).endswith(":latest")

    legacy_override = yaml.safe_load(
        (
            REPOSITORY_ROOT
            / "infra"
            / "production"
            / "compose.compact.legacy-www.yaml"
        ).read_text(encoding="utf-8")
    )
    assert legacy_override["networks"]["legacy-www"]["external"] is True
    compact_caddy = (
        REPOSITORY_ROOT / "infra" / "production" / "Caddyfile.compact"
    ).read_text(encoding="utf-8")
    www_redirect = (
        REPOSITORY_ROOT
        / "infra"
        / "production"
        / "Caddyfile.www-redirect"
    ).read_text(encoding="utf-8")
    production_library = (
        REPOSITORY_ROOT
        / "infra"
        / "production"
        / "scripts"
        / "lib.sh"
    ).read_text(encoding="utf-8")
    assert "import /etc/caddy/sites-enabled/*.caddy" in compact_caddy
    assert "reverse_proxy atc-frontend:8080" in compact_caddy
    assert "reverse_proxy web:8080" not in compact_caddy
    assert "www.{$ATC_DOMAIN}" in www_redirect
    assert "redir https://{$ATC_DOMAIN}{uri} permanent" in www_redirect
    assert '"${PRODUCTION_DIR}/Caddyfile.www-redirect" "${www_site}"' in (
        production_library
    )


def test_production_auth_and_workers_keep_least_privilege_boundaries() -> None:
    services = _compose()["services"]
    api_environment = services["api"]["environment"]
    assert api_environment["APP_ENV"] == "production"
    assert api_environment["AUTO_MIGRATE"] == "false"
    assert api_environment["SEED_DEMO_DATA"] == "false"
    assert (
        api_environment["BOOTSTRAP_TENANT_SLUG"]
        == "${BOOTSTRAP_TENANT_SLUG:?BOOTSTRAP_TENANT_SLUG is required}"
    )
    assert api_environment["AUTH_PROFILE"] == "enterprise_oidc"
    assert api_environment["KEYCLOAK_ADMIN_BASE_URL"] == "http://keycloak:8080"
    assert "OIDC_REDIRECT_URIS" in api_environment
    assert "OIDC_REDIRECT_URI" not in api_environment
    assert api_environment["RATE_LIMIT_ENABLED"] == "true"
    assert api_environment["REDIS_URL"].startswith("redis://")
    assert api_environment["IMAGE_INTELLIGENCE_PROFILE"] == "${IMAGE_INTELLIGENCE_PROFILE:-disabled}"

    forbidden_worker_secrets = {
        "AUTH_DATABASE_URL",
        "AUTH_JWT_SECRET",
        "AUTH_TOKEN_PEPPER",
        "OIDC_CLIENT_ID",
        "OIDC_CLIENT_SECRET",
        "OIDC_BOOTSTRAP_ADMIN_EMAIL",
        "REDIS_URL",
    }
    for name in ("tenant-worker", "product-event-consumer"):
        assert forbidden_worker_secrets.isdisjoint(services[name]["environment"])
    tenant_environment = services["tenant-worker"]["environment"]
    assert "atc_worker:" in tenant_environment["DATABASE_URL"]
    assert "atc_scheduler:" in tenant_environment["TENANT_DIRECTORY_DATABASE_URL"]
    assert services["tenant-worker"]["command"][-1] == "scripts.run_tenant_workers"
    assert "ATC_WORKER_TENANT_ID" not in PRODUCTION_COMPOSE.read_text(encoding="utf-8")


def test_keycloak_import_and_public_management_boundary_are_fail_closed() -> None:
    services = _compose()["services"]
    keycloak = services["keycloak"]
    assert keycloak["image"] == "quay.io/keycloak/keycloak:26.7.0"
    assert keycloak["user"] == "1000:0"
    assert keycloak["volumes"] == [
        "../../.runtime/keycloak/atc-realm.json:/opt/keycloak/data/import/atc-realm.json:ro"
    ]
    realm = (
        REPOSITORY_ROOT
        / "infra"
        / "production"
        / "keycloak"
        / "atc-realm.json.template"
    ).read_text(encoding="utf-8")
    assert '"emailVerified": true' in realm
    assert '"registrationEmailAsUsername": false' in realm
    assert '"loginWithEmailAllowed": true' in realm
    assert '"standardFlowEnabled": false' in realm
    assert '"directAccessGrantsEnabled": true' in realm
    assert '"serviceAccountsEnabled": true' in realm
    assert '"requiredActions": []' in realm
    assert '"temporary": false' in realm
    assert '"eventsEnabled": true' in realm
    assert '"adminEventsEnabled": true' in realm
    assert '"adminEventsDetailsEnabled": true' in realm
    assert '"smtpServer"' in realm
    assert '"resetPasswordAllowed": true' in realm
    assert (
        '"post.logout.redirect.uris": "https://__ATC_DOMAIN__/login"' in realm
    )
    assert "__OIDC_CLIENT_SECRET__" in realm

    caddy = (
        REPOSITORY_ROOT / "infra" / "production" / "Caddyfile"
    ).read_text(encoding="utf-8")
    for path in ("/admin/*", "/realms/master/*", "/health/*", "/metrics/*"):
        assert path in caddy
    assert "Strict-Transport-Security" in caddy
    assert "@oidc_callback path /login/callback" in caddy
    assert 'header @oidc_callback Referrer-Policy "no-referrer"' in caddy
    assert "log {" not in caddy

    provision_wrapper = (
        REPOSITORY_ROOT / "infra" / "production" / "keycloak-provision-user.sh"
    ).read_text(encoding="utf-8")
    assert (
        "compose_with_ops run --rm --no-deps keycloak-user-provisioner"
        in provision_wrapper
    )
    assert "--allow-internal-keycloak-http" in provision_wrapper
    assert "acquire_global_operation_lock" in provision_wrapper
    assert "--admin-password" not in provision_wrapper
    assert "--send-actions-email" in provision_wrapper
    assert '--username "${login_identifier}"' in provision_wrapper
    assert "--email-verified" in provision_wrapper
    assert '--redirect-uri "https://${ATC_DOMAIN}/login"' in provision_wrapper
    assert 'mode="${3:-}"' not in provision_wrapper

    admin_login_wrapper = (
        REPOSITORY_ROOT / "infra" / "production" / "keycloak-admin-login.sh"
    ).read_text(encoding="utf-8")
    assert 'load_production_env' in admin_login_wrapper
    assert '--user "${KEYCLOAK_ADMIN_USERNAME}"' in admin_login_wrapper
    assert "KEYCLOAK_ADMIN_PASSWORD" not in admin_login_wrapper

    reconcile_wrapper = (
        REPOSITORY_ROOT / "infra" / "production" / "keycloak-reconcile.sh"
    ).read_text(encoding="utf-8")
    assert (
        "compose_with_ops run -T --rm --no-deps keycloak-reconciler"
        in reconcile_wrapper
    )
    assert "--allow-internal-keycloak-http" in reconcile_wrapper
    assert 'printf \'%s\\n%s\\n\'' in reconcile_wrapper
    assert "--admin-password" not in reconcile_wrapper
    reconcile_source = (
        REPOSITORY_ROOT / "apps" / "api" / "scripts" / "reconcile_keycloak_realm.py"
    ).read_text(encoding="utf-8")
    assert "--admin-password" not in reconcile_source
    assert 'SERVICE_ACCOUNT_REALM_MANAGEMENT_ROLES = ("manage-users",)' in (
        reconcile_source
    )


def test_keycloak_realm_renderer_json_escapes_environment_values(
    tmp_path: Path,
) -> None:
    template = (
        REPOSITORY_ROOT
        / "infra"
        / "production"
        / "keycloak"
        / "atc-realm.json.template"
    )
    renderer = (
        REPOSITORY_ROOT
        / "infra"
        / "production"
        / "scripts"
        / "render_keycloak_realm.py"
    )
    output = tmp_path / "realm.json"
    email = "owner+ops&/cn@example.cn"
    initial_password = 'Aa1!quote"slash\\amp&less<'
    environment = {
        **os.environ,
        "ATC_DOMAIN": "catalog.example.cn",
        "OIDC_CLIENT_ID": "atc-web",
        "OIDC_CLIENT_SECRET": "a" * 64,
        "OIDC_BOOTSTRAP_ADMIN_EMAIL": email,
        "KEYCLOAK_INITIAL_USER_PASSWORD": initial_password,
        "KEYCLOAK_SMTP_HOST": "smtp.example.cn",
        "KEYCLOAK_SMTP_PORT": "587",
        "KEYCLOAK_SMTP_FROM": "no-reply@example.cn",
        "KEYCLOAK_SMTP_REPLY_TO": "support@example.cn",
        "KEYCLOAK_SMTP_USERNAME": "smtp-user@example.cn",
        "KEYCLOAK_SMTP_PASSWORD": "c" * 32,
    }
    subprocess.run(
        [sys.executable, str(renderer), str(template), str(output)],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    realm = json.loads(output.read_text(encoding="utf-8"))
    assert realm["users"][0]["email"] == email
    assert realm["users"][0]["username"] == email
    assert realm["users"][0]["credentials"][0]["value"] == initial_password
    assert realm["clients"][0]["redirectUris"] == [
        "https://catalog.example.cn/login/callback",
        "https://catalog.example.cn/login",
    ]
    assert realm["smtpServer"]["password"] == "c" * 32
    assert output.stat().st_mode & 0o777 == 0o600


def test_keycloak_initial_password_validation_matches_realm_policy() -> None:
    validator = (
        REPOSITORY_ROOT
        / "infra"
        / "production"
        / "scripts"
        / "validate_env.sh"
    ).read_text(encoding="utf-8")
    hex_secret_block = validator.split("secret_values=(", 1)[1].split(
        "\n)", 1
    )[0]
    assert "KEYCLOAK_INITIAL_USER_PASSWORD" not in hex_secret_block
    assert "initial_user_password" in validator
    for password_class in (
        "[A-Za-z]",
        "[[:digit:]]",
        "[[:space:]]",
    ):
        assert password_class in validator
    assert ">= 8" in validator
    assert "<= 128" in validator
    assert "uppercase letter" not in validator
    assert "lowercase letter" not in validator
    assert "special character" not in validator

    realm_template = json.loads(
        (
            REPOSITORY_ROOT
            / "infra"
            / "production"
            / "keycloak"
            / "atc-realm.json.template"
        ).read_text(encoding="utf-8")
    )
    assert realm_template["passwordPolicy"] == (
        r"length(8) and maxLength(128) and digits(1) and "
        r"regexPattern(^(?=.*[A-Za-z])\S+$) and notUsername(undefined) "
        r"and notEmail(undefined)"
    )

    for password in ("Simple42", "ABCDEFG1", "abcdefg1", "Abcd!234"):
        assert _valid_password(password, "owner@example.test", "owner")
    for password in (
        "short1",
        "12345678",
        "abcdefgh",
        "Abcd 123",
        "A1" + "b" * 127,
        "OWNER@EXAMPLE.TEST",
        "OWNER",
    ):
        assert not _valid_password(password, "owner@example.test", "owner")

    reset_script = (
        REPOSITORY_ROOT
        / "infra"
        / "production"
        / "keycloak-reset-user-password.sh"
    ).read_text(encoding="utf-8")
    assert ">= 8" in reset_script
    assert "<= 128" in reset_script
    assert "[A-Za-z]" in reset_script
    assert "[0-9]" in reset_script
    assert "[[:space:]]" in reset_script
    assert "special character" not in reset_script

    example = (REPOSITORY_ROOT / ".env.production.example").read_text(
        encoding="utf-8"
    )
    assert (
        "KEYCLOAK_INITIAL_USER_PASSWORD="
        "'REPLACE_WITH_STRONG_MIXED_INITIAL_PASSWORD'"
    ) in example
    assert "printf 'Aa1!%s\\n'" in example


def test_keycloak_realm_renderer_omits_smtp_only_when_explicitly_disabled(
    tmp_path: Path,
) -> None:
    template = (
        REPOSITORY_ROOT
        / "infra"
        / "production"
        / "keycloak"
        / "atc-realm.json.template"
    )
    renderer = (
        REPOSITORY_ROOT
        / "infra"
        / "production"
        / "scripts"
        / "render_keycloak_realm.py"
    )
    output = tmp_path / "realm-without-smtp.json"
    environment = {
        **os.environ,
        "ATC_ENABLE_SMTP": "false",
        "ATC_DOMAIN": "catalog.example.cn",
        "OIDC_CLIENT_ID": "atc-web",
        "OIDC_CLIENT_SECRET": "a" * 64,
        "OIDC_BOOTSTRAP_ADMIN_EMAIL": "owner@example.cn",
        "KEYCLOAK_INITIAL_USER_PASSWORD": "Aa1!" + "b" * 60,
    }
    for name in (
        "KEYCLOAK_SMTP_HOST",
        "KEYCLOAK_SMTP_PORT",
        "KEYCLOAK_SMTP_FROM",
        "KEYCLOAK_SMTP_REPLY_TO",
        "KEYCLOAK_SMTP_USERNAME",
        "KEYCLOAK_SMTP_PASSWORD",
    ):
        environment.pop(name, None)
    subprocess.run(
        [sys.executable, str(renderer), str(template), str(output)],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    realm = json.loads(output.read_text(encoding="utf-8"))
    assert "smtpServer" not in realm
    assert realm["users"][0]["emailVerified"] is True
    assert realm["users"][0]["requiredActions"] == []
    assert realm["users"][0]["credentials"][0]["temporary"] is False


def test_sensitive_query_strings_are_excluded_from_every_http_access_log() -> None:
    nginx = (REPOSITORY_ROOT / "apps" / "web" / "nginx.conf").read_text(
        encoding="utf-8"
    )
    assert "map $request_uri $atc_access_loggable" in nginx
    assert (
        r"~^/api/(?:quotes|v1/public-quote-drafts)/[^/]+/(?:pdf|xlsx)(?:\?|$) 0;"
        in nginx
    )
    assert r"~^/login/callback(?:\?|$) 0;" in nginx
    assert 'log_format atc_safe \'$remote_addr "$request_method $uri"\';' in nginx
    log_format = nginx.split("log_format atc_safe", 1)[1].split(";", 1)[0]
    assert "$remote_addr" in log_format
    assert "$request_method $uri" in log_format
    for forbidden in ("$request_uri", "$request ", "$http_referer", "$http_"):
        assert forbidden not in log_format
    assert "combined" not in nginx
    assert "access_log /dev/stdout atc_safe if=$atc_access_loggable;" in nginx
    assert "set_real_ip_from 172.31.10.0/24;" in nginx
    assert "set_real_ip_from 172.31.20.0/24;" in nginx
    assert "limit_req zone=atc_api_per_ip" in nginx
    assert "client_max_body_size 260m;" in nginx
    assert "X-Quote-Download-Token" not in nginx
    assert 'default "no-store, no-cache, must-revalidate";' in nginx
    assert (
        '~^/assets/.*:(200|206|304)$ "public, max-age=31536000, immutable";'
        in nginx
    )
    assert "~^/api/ \"\";" in nginx
    assert 'add_header Cache-Control $atc_cache_control always;' in nginx


def test_production_secrets_are_excluded_from_root_docker_build_context() -> None:
    dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8")
    ignored = {
        line.strip()
        for line in dockerignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert ".env.*" in ignored
    assert ".runtime" in ignored
    assert ".deployments" in ignored


def test_deploy_and_backup_contract_never_delete_persistent_volumes() -> None:
    deploy = (
        REPOSITORY_ROOT / "infra" / "production" / "deploy.sh"
    ).read_text(encoding="utf-8")
    backup = (
        REPOSITORY_ROOT / "infra" / "production" / "backup.sh"
    ).read_text(encoding="utf-8")
    restore = (
        REPOSITORY_ROOT / "infra" / "production" / "restore.sh"
    ).read_text(encoding="utf-8")
    for forbidden in ("down --volumes", "down -v", "docker volume rm"):
        assert forbidden not in deploy
        assert forbidden not in backup
        assert forbidden not in restore
    assert deploy.index("db-bootstrap") < deploy.index("db-migrate")
    assert deploy.index("db-migrate") < deploy.index("db-grants")
    assert deploy.index("db-grants") < deploy.index("production-bootstrap")
    assert deploy.index("production-bootstrap") < deploy.index("dependency-bootstrap")
    assert deploy.index("dependency-bootstrap") < deploy.index("keycloak-reconcile.sh")
    assert deploy.index("keycloak-reconcile.sh") < deploy.index(
        "rolling out API, web, and TLS edge"
    )
    assert "rollback_on_error" in deploy
    assert "stopping the unrecorded first-release public workloads" in deploy
    assert "git checkout --detach" in deploy
    assert "acquire_global_operation_lock" in deploy
    assert deploy.index('"${SCRIPT_DIR}/backup.sh"') < deploy.index("db-migrate")
    assert "ATC_CONFIRMED_EXPAND_CONTRACT" in deploy
    assert "application.postgresql.dump" in backup
    assert "keycloak.postgresql.dump" in backup
    assert "backup-minio" in backup
    assert "backup-rabbitmq" in backup
    assert "SHA256SUMS" in backup
    assert "compose stop caddy web api keycloak" in backup
    assert "resume_writers" in backup
    assert "last-backup-path" in backup
    assert 'restic backup "${final}"' in backup
    assert 'if [[ -n "${RESTIC_REPOSITORY:-}" ]]' not in backup
    assert "RESTIC_REPOSITORY" in (
        REPOSITORY_ROOT / "infra" / "production" / "scripts" / "validate_env.sh"
    ).read_text(encoding="utf-8")
    assert deploy.index("mandatory initial local backup") < deploy.index(
        "write_release_metadata"
    )
    assert 'if [[ "${ATC_ENABLE_REMOTE_BACKUP}" == "true" ]]' in backup
    assert "backup-local-objects" in backup
    assert "ATC_DEPLOYMENT_PROFILE" in deploy
    assert "compact production requires at least 3 GiB RAM" in deploy
    assert "COMPOSE_PARALLEL_LIMIT=1" in deploy
    assert "ATC_COMPACT_SWAP_GIB" in deploy
    assert (
        "compose up --detach --wait postgres redis keycloak-postgres keycloak\n"
        in deploy
    )
    assert "compose run --rm --no-deps object-storage-bootstrap" in deploy
    assert deploy.index(
        "compose up --detach --wait postgres redis keycloak-postgres keycloak"
    ) < deploy.index("compose run --rm --no-deps object-storage-bootstrap")
    compact_api_dependencies = _compact_compose()["services"]["api"]["depends_on"]
    assert "object-storage-bootstrap" not in compact_api_dependencies
    restic_initializer = (
        REPOSITORY_ROOT / "infra" / "production" / "restic-init.sh"
    ).read_text(encoding="utf-8")
    assert "restic init" in restic_initializer
    assert "acquire_global_operation_lock" in restic_initializer
    assert "restore-minio" in restore
    assert "restore-rabbitmq" in restore
    assert "ai_trade_cloud_restore" in restore
    assert "keycloak_restore" in restore
    assert restore.index("keycloak-reconcile.sh") < restore.index(
        "compose up --detach --no-deps --wait api web caddy"
    )

    web_build = _compose()["services"]["web"]["build"]["args"]
    assert (
        web_build["VITE_PRIMARY_STOREFRONT_SLUG"]
        == "${BOOTSTRAP_TENANT_NAME:?BOOTSTRAP_TENANT_NAME is required}"
    )
    assert (
        web_build["VITE_LEGAL_OPERATOR_NAME"]
        == "${LEGAL_OPERATOR_NAME:?LEGAL_OPERATOR_NAME is required}"
    )
    assert (
        web_build["VITE_PRIVACY_CONTACT_EMAIL"]
        == "${PRIVACY_CONTACT_EMAIL:?PRIVACY_CONTACT_EMAIL is required}"
    )
    assert (
        web_build["VITE_PRIVACY_EFFECTIVE_DATE"]
        == "${PRIVACY_EFFECTIVE_DATE:-2026-07-23}"
    )


def test_tenant_worker_empty_bootstrap_and_multi_tenant_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_tenant_workers, "active_tenant_ids", lambda _url: ())
    assert run_tenant_workers.run_cycle(
        directory_url="postgresql://directory",
        worker_id="worker",
        relay_id="relay",
    ) == (0, False)

    tenants = (uuid4(), uuid4())
    file_seen: list[object] = []
    knowledge_seen: list[object] = []
    support_ai_seen: list[object] = []
    relay_seen: list[object] = []
    monkeypatch.setattr(
        run_tenant_workers, "active_tenant_ids", lambda _url: tenants
    )
    monkeypatch.setattr(
        run_tenant_workers,
        "process_file_once",
        lambda *, tenant_id, worker_id: file_seen.append((tenant_id, worker_id))
        is None
        and False,
    )
    monkeypatch.setattr(
        run_tenant_workers,
        "process_support_knowledge_once",
        lambda *, tenant_id, worker_id: knowledge_seen.append(
            (tenant_id, worker_id)
        )
        is None
        and False,
    )
    monkeypatch.setattr(
        run_tenant_workers,
        "process_support_ai_once",
        lambda *, tenant_id, worker_id: support_ai_seen.append(
            (tenant_id, worker_id)
        )
        is None
        and False,
    )
    monkeypatch.setattr(
        run_tenant_workers,
        "relay_outbox_once",
        lambda *, tenant_id, relay_id: relay_seen.append((tenant_id, relay_id))
        is None
        and tenant_id == tenants[1],
    )
    assert run_tenant_workers.run_cycle(
        directory_url="postgresql://directory",
        worker_id="worker",
        relay_id="relay",
    ) == (2, True)
    assert [row[0] for row in file_seen] == list(tenants)
    assert [row[0] for row in knowledge_seen] == list(tenants)
    assert [row[0] for row in support_ai_seen] == list(tenants)
    assert [row[0] for row in relay_seen] == list(tenants)
