"""Unify storefront product priority and category priority settings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260908_0137"
down_revision = "20260908_0136"
branch_labels = depends_on = None


def upgrade():
    op.add_column("tenant_public_profiles", sa.Column("storefront_sorting_config", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True))


def downgrade():
    op.drop_column("tenant_public_profiles", "storefront_sorting_config")
