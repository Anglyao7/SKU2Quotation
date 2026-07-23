"""One-time, idempotent production tenant/OWNER bootstrap.

Run this as a one-off administrative job with the migration/table-owner
database URL. Runtime API credentials are intentionally insufficient for
cross-tenant bootstrap under PostgreSQL RLS.
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.production_bootstrap import bootstrap_production_owner


def _required(value: str | None, name: str) -> str:
    if value and value.strip():
        return value.strip()
    raise SystemExit(f"{name} is required")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--organization-code", default=os.getenv("BOOTSTRAP_ORGANIZATION_CODE"))
    parser.add_argument("--organization-name", default=os.getenv("BOOTSTRAP_ORGANIZATION_NAME"))
    parser.add_argument("--tenant-slug", default=os.getenv("BOOTSTRAP_TENANT_SLUG"))
    parser.add_argument("--tenant-name", default=os.getenv("BOOTSTRAP_TENANT_NAME"))
    parser.add_argument("--owner-email", default=os.getenv("BOOTSTRAP_OWNER_EMAIL"))
    parser.add_argument("--owner-name", default=os.getenv("BOOTSTRAP_OWNER_NAME"))
    parser.add_argument(
        "--platform-admin",
        action="store_true",
        default=os.getenv("BOOTSTRAP_PLATFORM_ADMIN", "false").lower()
        in {"1", "true", "yes", "on"},
    )
    arguments = parser.parse_args()
    app_env = os.getenv("APP_ENV", "development").lower()
    database_url = os.getenv("ATC_BOOTSTRAP_DATABASE_URL")
    if app_env in {"staging", "production", "prod"} and not database_url:
        raise SystemExit(
            "ATC_BOOTSTRAP_DATABASE_URL is required in managed environments"
        )
    database_url = database_url or os.getenv("DATABASE_URL")
    engine = create_engine(
        _required(database_url, "ATC_BOOTSTRAP_DATABASE_URL"),
        pool_pre_ping=True,
    )
    with Session(engine) as session:
        result = bootstrap_production_owner(
            session,
            organization_code=_required(
                arguments.organization_code, "BOOTSTRAP_ORGANIZATION_CODE"
            ),
            organization_name=_required(
                arguments.organization_name, "BOOTSTRAP_ORGANIZATION_NAME"
            ),
            tenant_slug=_required(arguments.tenant_slug, "BOOTSTRAP_TENANT_SLUG"),
            tenant_name=_required(arguments.tenant_name, "BOOTSTRAP_TENANT_NAME"),
            owner_email=_required(arguments.owner_email, "BOOTSTRAP_OWNER_EMAIL"),
            owner_display_name=_required(
                arguments.owner_name, "BOOTSTRAP_OWNER_NAME"
            ),
            platform_admin=arguments.platform_admin,
        )
    print(
        "Production bootstrap complete: "
        f"organization={result.organization_id} "
        f"tenant={result.tenant_id} "
        f"user={result.user_id} "
        f"membership={result.membership_id} "
        f"pending_oidc={str(result.pending_identity).lower()}"
    )


if __name__ == "__main__":
    main()
