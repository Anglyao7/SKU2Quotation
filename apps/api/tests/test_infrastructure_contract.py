from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.adapters.rabbitmq_topology import queue_arguments, topology_from_environment
from scripts.bootstrap_postgres_roles import validated_role_name


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPOSITORY_ROOT / "infra" / "local" / "compose.yaml"


def _compose() -> dict[str, object]:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_local_compose_declares_pinned_private_dependencies() -> None:
    value = _compose()
    services = value["services"]
    required = {
        "postgres",
        "redis",
        "rabbitmq",
        "minio",
        "db-bootstrap",
        "db-migrate",
        "db-grants",
        "dependency-bootstrap",
        "api",
        "file-worker",
        "outbox-relay",
        "product-event-consumer",
        "web",
    }
    assert required <= set(services)
    for service in services.values():
        image = service.get("image")
        if image:
            assert not image.endswith(":latest")
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:")

    assert value["networks"]["data"]["internal"] is True
    assert services["api"]["environment"]["ATC_PERSISTENCE_MODE"] == "postgresql"
    assert services["file-worker"]["environment"]["DATABASE_URL"].startswith(
        "postgresql+psycopg://atc_worker:"
    )

    image_targets: dict[str, str | None] = {}
    for service in services.values():
        build = service.get("build")
        image = service.get("image")
        if not image or not isinstance(build, dict):
            continue
        target = build.get("target")
        if image in image_targets:
            assert image_targets[image] == target
        image_targets[image] = target


def test_workload_dockerfiles_make_runtime_identity_explicit() -> None:
    api = (REPOSITORY_ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    web = (REPOSITORY_ROOT / "apps" / "web" / "Dockerfile").read_text(encoding="utf-8")
    minio = (REPOSITORY_ROOT / "infra" / "images" / "minio" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "USER 10001:10001" in api
    assert "USER 101" in web
    assert "USER 10002:10002" in minio


def test_quorum_queue_has_bounded_delivery_and_dead_letter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RABBITMQ_QUEUE_TYPE", "quorum")
    monkeypatch.setenv("RABBITMQ_DELIVERY_LIMIT", "7")
    monkeypatch.setenv("RABBITMQ_DEAD_LETTER_EXCHANGE", "atc.test-dead-letter")
    topology = topology_from_environment()
    assert queue_arguments(topology) == {
        "x-queue-type": "quorum",
        "x-delivery-limit": 7,
        "x-dead-letter-exchange": "atc.test-dead-letter",
    }


def test_postgres_role_names_are_strictly_validated() -> None:
    assert validated_role_name("atc_worker") == "atc_worker"
    for invalid in ("ATC-worker", "atc worker", 'atc_worker" SUPERUSER', "1atc"):
        with pytest.raises(ValueError):
            validated_role_name(invalid)


@pytest.mark.parametrize("grant_fails", [False, True])
def test_runtime_role_grants_publish_in_one_transaction(monkeypatch, grant_fails) -> None:
    from unittest.mock import MagicMock
    from scripts import grant_runtime_roles as grants

    connect = MagicMock()
    connection = connect.return_value
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        (name,) for name in sorted(
            set(grants.AUTH_TABLE_GRANTS) | grants.WORKER_TABLES
            | grants.WORKER_READ_ONLY_TABLES | {"alembic_version"}
        )
    ]
    monkeypatch.setenv("ATC_POSTGRES_OWNER_URL", "postgresql://test/db")
    monkeypatch.setattr(grants.psycopg, "connect", connect)
    if grant_fails:
        monkeypatch.setattr(grants, "_grant_tables", MagicMock(side_effect=RuntimeError("grant failed")))
        with pytest.raises(RuntimeError, match="grant failed"):
            grants.grant_runtime_roles()
        assert connection.__exit__.call_args.args[0] is RuntimeError
    else:
        grants.grant_runtime_roles()
        assert connection.__exit__.call_args.args == (None, None, None)
    connect.assert_called_once_with("postgresql://test/db", autocommit=False)
    connection.commit.assert_not_called()
