from __future__ import annotations

import argparse
import os
import time
from uuid import UUID

from app.database import SessionLocal
from app.workers.outbox_relay import relay_one_outbox_event


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one tenant-scoped Outbox Relay shard")
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    relay_id = os.getenv("OUTBOX_RELAY_ID", "atc-outbox-relay-1")
    while True:
        with SessionLocal() as session:
            result = relay_one_outbox_event(
                session,
                tenant_id=args.tenant_id,
                relay_id=relay_id,
            )
        print(
            f"status={result.status} outcome={result.outcome} "
            f"event_id={result.event_id or '-'} attempts={result.attempt_count}",
            flush=True,
        )
        if args.once:
            return
        if result.status == "IDLE":
            time.sleep(1.0)


if __name__ == "__main__":
    main()
