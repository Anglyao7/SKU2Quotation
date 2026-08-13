from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


API_ROOT = Path(__file__).resolve().parents[1]


def test_managed_sku_migration_backfills_and_restores_existing_codes(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "managed-sku-codes.db"
    migration_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(migration_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE tenants ("
            "id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT NOT NULL, "
            "timezone TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE products ("
            "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE skus ("
            "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, product_id TEXT NOT NULL, "
            "sku_code TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO tenants (id, name, slug, timezone) VALUES (?, ?, ?, ?)",
            ("1" * 32, "YoYo Trading", "yoyo", "Asia/Shanghai"),
        )
        connection.exec_driver_sql(
            "INSERT INTO products (id, tenant_id, created_at) VALUES "
            "(?, ?, ?), (?, ?, ?)",
            (
                "2" * 32,
                "1" * 32,
                "2026-08-12 16:10:00+00:00",
                "3" * 32,
                "1" * 32,
                "2026-08-12 17:10:00+00:00",
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO skus (id, tenant_id, product_id, sku_code, created_at) "
            "VALUES (?, ?, ?, ?, ?), (?, ?, ?, ?, ?), (?, ?, ?, ?, ?)",
            (
                "4" * 32,
                "1" * 32,
                "2" * 32,
                "SOURCE-A-RED",
                "2026-08-12 16:11:00+00:00",
                "5" * 32,
                "1" * 32,
                "2" * 32,
                "SOURCE-A-BLUE",
                "2026-08-12 16:12:00+00:00",
                "6" * 32,
                "1" * 32,
                "3" * 32,
                "SOURCE-B-RED",
                "2026-08-12 17:11:00+00:00",
            ),
        )
    engine.dispose()

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", migration_url)
    command.stamp(config, "20260813_0083")
    command.upgrade(config, "20260813_0084")

    upgraded_engine = create_engine(migration_url)
    inspector = inspect(upgraded_engine)
    assert "sku_prefix" in {
        column["name"] for column in inspector.get_columns("tenants")
    }
    assert {"sku_code_date", "sku_code_sequence"}.issubset(
        {column["name"] for column in inspector.get_columns("products")}
    )
    assert {"source_sku_code", "sku_sequence"}.issubset(
        {column["name"] for column in inspector.get_columns("skus")}
    )
    with upgraded_engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT sku_prefix FROM tenants"
        ).scalar_one() == "YOYO"
        products = connection.exec_driver_sql(
            "SELECT id, sku_code_date, sku_code_sequence FROM products ORDER BY id"
        ).mappings().all()
        assert [row["sku_code_date"] for row in products] == [
            "2026-08-13",
            "2026-08-13",
        ]
        assert [row["sku_code_sequence"] for row in products] == [1, 2]
        skus = connection.exec_driver_sql(
            "SELECT sku_code, source_sku_code, sku_sequence FROM skus "
            "ORDER BY product_id, created_at"
        ).mappings().all()
        assert [row["sku_code"] for row in skus] == [
            "YOYO-260813001-001",
            "YOYO-260813001-002",
            "YOYO-260813002-001",
        ]
        assert [row["source_sku_code"] for row in skus] == [
            "SOURCE-A-RED",
            "SOURCE-A-BLUE",
            "SOURCE-B-RED",
        ]
        assert [row["sku_sequence"] for row in skus] == [1, 2, 1]
    upgraded_engine.dispose()

    command.downgrade(config, "20260813_0083")
    downgraded_engine = create_engine(migration_url)
    with downgraded_engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT sku_code FROM skus ORDER BY product_id, created_at"
        ).scalars().all() == [
            "SOURCE-A-RED",
            "SOURCE-A-BLUE",
            "SOURCE-B-RED",
        ]
    downgraded_engine.dispose()
