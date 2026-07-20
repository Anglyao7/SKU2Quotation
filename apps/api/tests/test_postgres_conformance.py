import os

import pytest

from scripts.verify_postgres_rls import verify_postgres_rls
from scripts.verify_postgres_worker_role import verify_postgres_worker_role


OWNER_URL = os.environ.get("ATC_POSTGRES_OWNER_URL")
APP_URL = os.environ.get("ATC_POSTGRES_APP_URL")
WORKER_URL = os.environ.get("ATC_POSTGRES_WORKER_URL")


@pytest.mark.skipif(
    not OWNER_URL or not APP_URL,
    reason="real PostgreSQL conformance URLs are not configured",
)
def test_real_postgres_non_owner_rls_matrix() -> None:
    report = verify_postgres_rls(OWNER_URL, APP_URL)  # type: ignore[arg-type]
    assert report["status"] == "passed"
    assert report["application_role_superuser"] is False
    assert report["application_role_bypassrls"] is False
    assert all(value in {"allowed", "blocked"} for value in report["matrix"].values())


@pytest.mark.skipif(
    not OWNER_URL or not WORKER_URL,
    reason="real PostgreSQL worker conformance URLs are not configured",
)
def test_real_postgres_worker_role_rls_matrix() -> None:
    report = verify_postgres_worker_role(OWNER_URL, WORKER_URL)  # type: ignore[arg-type]
    assert report["status"] == "passed"
    assert report["worker_role_superuser"] is False
    assert report["worker_role_bypassrls"] is False
    assert report["worker_owned_tables"] == 0
