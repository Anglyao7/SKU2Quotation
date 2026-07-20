"""Allow TTL cleanup to erase temporary query vectors.

Revision ID: 20260718_0019
Revises: 20260718_0018
"""
from alembic import op
from pgvector.sqlalchemy import VECTOR
import sqlalchemy as sa

revision = "20260718_0019"
down_revision = "20260718_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    vector_type = VECTOR().with_variant(sa.JSON(), "sqlite")
    with op.batch_alter_table("image_searches") as batch:
        batch.alter_column("query_embedding", existing_type=vector_type, nullable=True)


def downgrade() -> None:
    vector_type = VECTOR().with_variant(sa.JSON(), "sqlite")
    op.execute("DELETE FROM image_searches WHERE query_embedding IS NULL")
    with op.batch_alter_table("image_searches") as batch:
        batch.alter_column("query_embedding", existing_type=vector_type, nullable=False)
