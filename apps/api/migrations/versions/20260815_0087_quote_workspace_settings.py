"""Persist merchant quote-workspace presentation settings.

Revision ID: 20260815_0087
Revises: 20260815_0086
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260815_0087"
down_revision = "20260815_0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("public_quote_drafts")}
    with op.batch_alter_table("public_quote_drafts") as batch:
        if "quotation_number" not in columns:
            batch.add_column(sa.Column("quotation_number", sa.String(80), nullable=True))
        if "document_style" not in columns:
            batch.add_column(
                sa.Column(
                    "document_style",
                    sa.String(24),
                    nullable=False,
                    server_default="indigo",
                )
            )
        if "quote_template_id" not in columns:
            batch.add_column(
                sa.Column(
                    "quote_template_id",
                    sa.Uuid(),
                    sa.ForeignKey("quote_excel_templates.id", ondelete="SET NULL"),
                    nullable=True,
                )
            )
        if "quotation_number" not in columns:
            batch.create_unique_constraint(
                "uq_public_quote_drafts_tenant_quotation_number",
                ["tenant_id", "quotation_number"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("public_quote_drafts")}
    with op.batch_alter_table("public_quote_drafts") as batch:
        if "quotation_number" in columns:
            batch.drop_constraint(
                "uq_public_quote_drafts_tenant_quotation_number",
                type_="unique",
            )
            batch.drop_column("quotation_number")
        if "quote_template_id" in columns:
            batch.drop_column("quote_template_id")
        if "document_style" in columns:
            batch.drop_column("document_style")
