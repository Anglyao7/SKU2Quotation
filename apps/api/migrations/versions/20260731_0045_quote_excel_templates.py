"""Add tenant quote Excel templates and item specification snapshots.

Revision ID: 20260731_0045
Revises: 20260730_0044
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260731_0045"
down_revision = "20260730_0044"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)
JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def upgrade() -> None:
    with op.batch_alter_table("public_quote_draft_items") as batch:
        batch.add_column(sa.Column("specification_snapshot", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column(
                "option_values_snapshot",
                JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )

    op.create_table(
        "quote_excel_templates",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("object_key", sa.String(1000), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sheet_names", JSON_DOCUMENT, nullable=False),
        sa.Column("sheet_name", sa.String(200), nullable=False),
        sa.Column("header_row", sa.Integer(), nullable=False),
        sa.Column("data_start_row", sa.Integer(), nullable=False),
        sa.Column("data_end_row", sa.Integer(), nullable=False),
        sa.Column("columns", JSON_DOCUMENT, nullable=False),
        sa.Column("column_mappings", JSON_DOCUMENT, nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_by_user_id", U(), nullable=True),
        sa.Column("updated_by_user_id", U(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "byte_size > 0",
            name="ck_quote_excel_templates_byte_size_positive",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_quote_excel_templates_sha256_length",
        ),
        sa.CheckConstraint(
            "header_row >= 1",
            name="ck_quote_excel_templates_header_row_positive",
        ),
        sa.CheckConstraint(
            "data_start_row > header_row",
            name="ck_quote_excel_templates_data_start_after_header",
        ),
        sa.CheckConstraint(
            "data_end_row >= data_start_row",
            name="ck_quote_excel_templates_data_end_after_start",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_quote_excel_templates_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_quote_excel_templates_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_quote_excel_templates_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_quote_excel_templates_updated_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quote_excel_templates"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_quote_excel_templates_tenant_identity",
        ),
    )
    op.create_index(
        "ix_quote_excel_templates_tenant_default",
        "quote_excel_templates",
        ["tenant_id", "is_default", "updated_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        op.execute('ALTER TABLE "quote_excel_templates" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "quote_excel_templates" FORCE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY "quote_excel_templates_tenant_isolation" '
            'ON "quote_excel_templates" FOR ALL '
            f"USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_quote_excel_templates_tenant_default",
        table_name="quote_excel_templates",
    )
    op.drop_table("quote_excel_templates")
    with op.batch_alter_table("public_quote_draft_items") as batch:
        batch.drop_column("option_values_snapshot")
        batch.drop_column("specification_snapshot")
