"""Run tenant-scoped file and outbox work across every active SaaS tenant.

Tenant discovery uses a dedicated BYPASSRLS role that can SELECT only
``tenants.id``, ``tenants.status``, and ``tenants.deleted_at``. Actual jobs use
the existing NOBYPASSRLS worker role and bind one tenant context before every
query. An empty tenant directory is a normal bootstrap state: the process waits
and discovers again.
"""

from __future__ import annotations

import os
import socket
import time
from uuid import UUID

import psycopg

from app.database import SessionLocal, set_request_context
from app.model_mixins import utcnow
from app.repositories.file_security_repository import next_due_job_id
from app.services.support_ai_knowledge import (
    claim_next_knowledge_ingestion,
    process_knowledge_ingestion,
)
from app.services.support_ai_orchestrator import (
    claim_next_support_ai_run,
    process_support_ai_run,
)
from app.support_ai_models import SupportAIRunRow
from app.workers.file_processing import process_file_worker_job
from app.workers.outbox_relay import relay_one_outbox_event
from scripts.bootstrap_postgres_roles import _psycopg_url


ZERO_UUID = UUID(int=0)


def _support_stale_seconds() -> int:
    try:
        value = int(os.getenv("SUPPORT_AI_STALE_JOB_SECONDS", "900"))
    except ValueError:
        value = 900
    return max(60, min(value, 86_400))


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def active_tenant_ids(directory_url: str) -> tuple[UUID, ...]:
    with psycopg.connect(_psycopg_url(directory_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM tenants "
                "WHERE status = 'active' AND deleted_at IS NULL ORDER BY id"
            )
            return tuple(UUID(str(row[0])) for row in cursor.fetchall())


def process_file_once(*, tenant_id: UUID, worker_id: str) -> bool:
    with SessionLocal() as session:
        set_request_context(
            session,
            organization_id=ZERO_UUID,
            tenant_id=tenant_id,
            user_id=ZERO_UUID,
        )
        job_id = next_due_job_id(session, tenant_id=tenant_id, now=utcnow())
        session.rollback()
        if job_id is None:
            return False
        result = process_file_worker_job(
            session,
            tenant_id=tenant_id,
            job_id=job_id,
            worker_id=worker_id,
        )
        print(
            f"tenant={tenant_id} file_job={result.job_id} "
            f"status={result.status} outcome={result.outcome}",
            flush=True,
        )
        return True


def relay_outbox_once(*, tenant_id: UUID, relay_id: str) -> bool:
    with SessionLocal() as session:
        result = relay_one_outbox_event(
            session,
            tenant_id=tenant_id,
            relay_id=relay_id,
        )
        if result.status != "IDLE":
            print(
                f"tenant={tenant_id} outbox_status={result.status} "
                f"outcome={result.outcome} event_id={result.event_id or '-'}",
                flush=True,
            )
        return result.status != "IDLE"


def process_support_knowledge_once(*, tenant_id: UUID, worker_id: str) -> bool:
    del worker_id
    with SessionLocal() as session:
        set_request_context(
            session,
            organization_id=ZERO_UUID,
            tenant_id=tenant_id,
            user_id=ZERO_UUID,
        )
        claimed = claim_next_knowledge_ingestion(
            session,
            tenant_id=tenant_id,
            stale_after_seconds=_support_stale_seconds(),
        )
    if claimed is None:
        return False
    source_id, job_id = claimed
    process_knowledge_ingestion(
        tenant_id=tenant_id,
        source_id=source_id,
        job_id=job_id,
    )
    print(
        f"tenant={tenant_id} support_knowledge_job={job_id} processed=true",
        flush=True,
    )
    return True


def process_support_ai_once(*, tenant_id: UUID, worker_id: str) -> bool:
    del worker_id
    with SessionLocal() as session:
        set_request_context(
            session,
            organization_id=ZERO_UUID,
            tenant_id=tenant_id,
            user_id=ZERO_UUID,
        )
        run_id = claim_next_support_ai_run(
            session,
            tenant_id=tenant_id,
            stale_after_seconds=_support_stale_seconds(),
        )
        if run_id is None:
            return False
        process_support_ai_run(session, run_id=run_id)
        run = session.get(SupportAIRunRow, run_id)
        print(
            f"tenant={tenant_id} support_ai_run={run_id} "
            f"status={run.status if run is not None else 'missing'}",
            flush=True,
        )
        return True


def run_cycle(*, directory_url: str, worker_id: str, relay_id: str) -> tuple[int, bool]:
    tenant_ids = active_tenant_ids(directory_url)
    did_work = False
    for tenant_id in tenant_ids:
        try:
            did_work = (
                process_file_once(tenant_id=tenant_id, worker_id=worker_id)
                or did_work
            )
            did_work = (
                process_support_knowledge_once(
                    tenant_id=tenant_id,
                    worker_id=worker_id,
                )
                or did_work
            )
            did_work = (
                process_support_ai_once(
                    tenant_id=tenant_id,
                    worker_id=worker_id,
                )
                or did_work
            )
            did_work = (
                relay_outbox_once(tenant_id=tenant_id, relay_id=relay_id)
                or did_work
            )
        except Exception as exc:
            # One tenant cannot terminate or starve the other tenant shards.
            print(
                f"tenant={tenant_id} worker_error={type(exc).__name__}; continuing",
                flush=True,
            )
    return len(tenant_ids), did_work


def main() -> None:
    directory_url = _required("TENANT_DIRECTORY_DATABASE_URL")
    hostname = socket.gethostname()
    worker_id = os.getenv("WORKER_ID", f"{hostname}:{os.getpid()}")
    relay_id = os.getenv("OUTBOX_RELAY_ID", f"{hostname}:{os.getpid()}")
    idle_sleep = max(0.25, float(os.getenv("WORKER_IDLE_SLEEP_SECONDS", "2")))
    discovery_sleep = max(
        idle_sleep,
        float(os.getenv("TENANT_DISCOVERY_INTERVAL_SECONDS", "15")),
    )

    while True:
        try:
            _tenant_count, did_work = run_cycle(
                directory_url=directory_url,
                worker_id=worker_id,
                relay_id=relay_id,
            )
        except Exception as exc:
            print(
                f"tenant_directory_error={type(exc).__name__}; retrying",
                flush=True,
            )
            time.sleep(discovery_sleep)
            continue
        time.sleep(idle_sleep if did_work else discovery_sleep)


if __name__ == "__main__":
    main()
