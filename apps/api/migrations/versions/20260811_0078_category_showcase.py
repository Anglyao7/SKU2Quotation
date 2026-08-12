"""Add storefront category showcase settings and category cover sources.

Revision ID: 20260811_0078
Revises: 20260811_0077
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260811_0078"
down_revision = "20260811_0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        category_columns = {
            column["name"]
            for column in sa.inspect(op.get_bind()).get_columns("product_categories")
        }
        if "cover_source" not in category_columns:
            op.add_column(
                "product_categories",
                sa.Column(
                    "cover_source",
                    sa.String(20),
                    nullable=False,
                    server_default="NONE",
                ),
            )
        if "cover_object_key" not in category_columns:
            op.add_column(
                "product_categories",
                sa.Column("cover_object_key", sa.String(1000), nullable=True),
            )
        if "cover_product_id" not in category_columns:
            op.add_column(
                "product_categories",
                sa.Column("cover_product_id", sa.Uuid(as_uuid=True), nullable=True),
            )
        profile_columns = {
            column["name"]
            for column in sa.inspect(op.get_bind()).get_columns(
                "tenant_public_profiles"
            )
        }
        if "category_showcase_enabled" not in profile_columns:
            op.add_column(
                "tenant_public_profiles",
                sa.Column(
                    "category_showcase_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                ),
            )
        return

    with op.batch_alter_table("product_categories") as batch:
        batch.add_column(
            sa.Column(
                "cover_source",
                sa.String(20),
                nullable=False,
                server_default="NONE",
            )
        )
        batch.add_column(sa.Column("cover_object_key", sa.String(1000), nullable=True))
        batch.add_column(
            sa.Column("cover_product_id", sa.Uuid(as_uuid=True), nullable=True)
        )
        batch.create_check_constraint(
            "ck_product_categories_cover_source_allowed",
            "cover_source IN ('NONE', 'UPLOAD', 'PRODUCT')",
        )

    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.add_column(
            sa.Column(
                "category_showcase_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        profile_columns = {
            column["name"]
            for column in sa.inspect(op.get_bind()).get_columns(
                "tenant_public_profiles"
            )
        }
        if "category_showcase_enabled" in profile_columns:
            op.drop_column("tenant_public_profiles", "category_showcase_enabled")
        category_columns = {
            column["name"]
            for column in sa.inspect(op.get_bind()).get_columns("product_categories")
        }
        for column_name in (
            "cover_product_id",
            "cover_object_key",
            "cover_source",
        ):
            if column_name in category_columns:
                op.drop_column("product_categories", column_name)
        return

    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_column("category_showcase_enabled")

    with op.batch_alter_table("product_categories") as batch:
        batch.drop_constraint(
            "ck_product_categories_cover_source_allowed",
            type_="check",
        )
        batch.drop_column("cover_product_id")
        batch.drop_column("cover_object_key")
        batch.drop_column("cover_source")
