"""Make identities extensible and add account-level permission ceilings.

Revision ID: 20260810_0075
Revises: 20260810_0074
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260810_0075"
down_revision = "20260810_0074"
branch_labels = None
depends_on = None


JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def upgrade() -> None:
    with op.batch_alter_table("merchant_identity_profiles") as batch:
        batch.drop_constraint(
            "ck_merchant_identity_profiles_code_allowed",
            type_="check",
        )
        batch.add_column(
            sa.Column(
                "is_system",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    op.execute(
        "UPDATE merchant_identity_profiles "
        "SET is_system = true WHERE code IN ('ADMIN', 'USER')"
    )

    with op.batch_alter_table("memberships") as batch:
        batch.add_column(
            sa.Column("permission_overrides", JSON_DOCUMENT, nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("memberships") as batch:
        batch.drop_column("permission_overrides")

    # A legacy schema can only represent the two built-in identities.
    op.execute(
        "UPDATE tenants SET identity_code = 'USER', module_access_mode = 'INHERIT' "
        "WHERE identity_code NOT IN ('ADMIN', 'USER')"
    )
    op.execute(
        "DELETE FROM merchant_identity_profiles "
        "WHERE code NOT IN ('ADMIN', 'USER')"
    )
    with op.batch_alter_table("merchant_identity_profiles") as batch:
        batch.drop_column("is_system")
        batch.create_check_constraint(
            "ck_merchant_identity_profiles_code_allowed",
            "code IN ('ADMIN', 'USER')",
        )
