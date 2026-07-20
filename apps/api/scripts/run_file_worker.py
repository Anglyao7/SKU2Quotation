"""Run durable quarantine scan/parse jobs for one trusted tenant shard."""

from __future__ import annotations

import argparse
import os
import socket
import time
from uuid import UUID

from app.database import SessionLocal, set_request_context
from app.repositories.file_security_repository import next_due_job_id
from app.workers.file_processing import process_file_worker_job
from app.model_mixins import utcnow


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--job-id", type=UUID)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    return parser


def main() -> None:
    args = _parser().parse_args()
    worker_id = os.getenv("WORKER_ID", f"{socket.gethostname()}:{os.getpid()}")
    while True:
        with SessionLocal() as session:
            set_request_context(
                session,
                organization_id=UUID(int=0),
                tenant_id=args.tenant_id,
                user_id=UUID(int=0),
            )
            job_id = args.job_id or next_due_job_id(
                session,
                tenant_id=args.tenant_id,
                now=utcnow(),
            )
            session.rollback()
            if job_id is not None:
                result = process_file_worker_job(
                    session,
                    tenant_id=args.tenant_id,
                    job_id=job_id,
                    worker_id=worker_id,
                )
                print(f"job={result.job_id} status={result.status} outcome={result.outcome}")
        if args.once or args.job_id:
            return
        time.sleep(max(0.1, args.poll_seconds))


if __name__ == "__main__":
    main()
