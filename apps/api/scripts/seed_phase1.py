"""Idempotent Phase 1 local/demo initialization script."""
from app.database import SessionLocal, run_migrations
from app.saas_seed import seed_saas_foundation


def main() -> None:
    run_migrations()
    with SessionLocal() as session:
        seed_saas_foundation(session)


if __name__ == "__main__":
    main()
