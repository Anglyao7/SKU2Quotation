from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


CORE_ENVIRONMENT_PLACEHOLDERS = {
    "__ATC_DOMAIN__": "ATC_DOMAIN",
    "__OIDC_CLIENT_ID__": "OIDC_CLIENT_ID",
    "__OIDC_CLIENT_SECRET__": "OIDC_CLIENT_SECRET",
    "__OIDC_BOOTSTRAP_ADMIN_EMAIL__": "OIDC_BOOTSTRAP_ADMIN_EMAIL",
    "__KEYCLOAK_INITIAL_USER_PASSWORD__": "KEYCLOAK_INITIAL_USER_PASSWORD",
}
SMTP_ENVIRONMENT_PLACEHOLDERS = {
    "__KEYCLOAK_SMTP_HOST__": "KEYCLOAK_SMTP_HOST",
    "__KEYCLOAK_SMTP_PORT__": "KEYCLOAK_SMTP_PORT",
    "__KEYCLOAK_SMTP_FROM__": "KEYCLOAK_SMTP_FROM",
    "__KEYCLOAK_SMTP_REPLY_TO__": "KEYCLOAK_SMTP_REPLY_TO",
    "__KEYCLOAK_SMTP_USERNAME__": "KEYCLOAK_SMTP_USERNAME",
    "__KEYCLOAK_SMTP_PASSWORD__": "KEYCLOAK_SMTP_PASSWORD",
}


def _enabled(value: str | None) -> bool:
    return (value or "").lower() in {"1", "true", "yes", "on"}


def replace_placeholders(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, replacement)
        return value
    if isinstance(value, list):
        return [replace_placeholders(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: replace_placeholders(item, replacements)
            for key, item in value.items()
        }
    return value


def render(template_path: Path, output_path: Path) -> None:
    smtp_enabled = _enabled(os.environ.get("ATC_ENABLE_SMTP", "true"))
    placeholders = dict(CORE_ENVIRONMENT_PLACEHOLDERS)
    if smtp_enabled:
        placeholders.update(SMTP_ENVIRONMENT_PLACEHOLDERS)

    replacements: dict[str, str] = {}
    for placeholder, environment_name in placeholders.items():
        value = os.environ.get(environment_name)
        if not value:
            raise RuntimeError(f"{environment_name} is required")
        replacements[placeholder] = value

    template = json.loads(template_path.read_text(encoding="utf-8"))
    if not smtp_enabled:
        template.pop("smtpServer", None)
    rendered = replace_placeholders(template, replacements)
    serialized = json.dumps(
        rendered,
        ensure_ascii=False,
        indent=2,
        separators=(",", ": "),
    )
    unresolved = [
        placeholder
        for placeholder in (
            *CORE_ENVIRONMENT_PLACEHOLDERS,
            *SMTP_ENVIRONMENT_PLACEHOLDERS,
        )
        if placeholder in serialized
    ]
    if unresolved:
        raise RuntimeError("Keycloak realm contains unresolved placeholders")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".atc-realm-",
        suffix=".json",
        dir=output_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(serialized)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output_path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} TEMPLATE OUTPUT")
    render(Path(sys.argv[1]), Path(sys.argv[2]))


if __name__ == "__main__":
    main()
