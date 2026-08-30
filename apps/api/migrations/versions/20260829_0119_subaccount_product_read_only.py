"""Make customer subaccount product access strictly read-only.

Revision ID: 20260829_0119
Revises: 20260829_0118
"""

from __future__ import annotations

from alembic import op


revision = "20260829_0119"
down_revision = "20260829_0118"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_memberships_subaccount_products_read_only"
PRODUCT_WRITE_PERMISSION_CODES = (
    "product.create",
    "product.edit",
    "product.import",
    "product.review",
    "product.cost.read",
    "product.cost.write",
    "catalog.publish",
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    denied_array = ", ".join(f"'{code}'" for code in PRODUCT_WRITE_PERMISSION_CODES)
    jsonb_removals = "".join(
        f" - '{code}'" for code in PRODUCT_WRITE_PERMISSION_CODES
    )
    op.execute(
        f"""
        UPDATE public.memberships
        SET permission_overrides = permission_overrides{jsonb_removals},
            permission_version = permission_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE account_scope = 'CUSTOMER_SUBACCOUNT'
          AND permission_overrides IS NOT NULL
          AND permission_overrides ?| ARRAY[{denied_array}]::text[]
        """
    )
    op.execute(
        f"""
        ALTER TABLE public.memberships
        ADD CONSTRAINT {CONSTRAINT_NAME}
        CHECK (
            account_scope <> 'CUSTOMER_SUBACCOUNT'
            OR permission_overrides IS NULL
            OR NOT (
                permission_overrides ?| ARRAY[{denied_array}]::text[]
            )
        )
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            f"ALTER TABLE public.memberships DROP CONSTRAINT IF EXISTS {CONSTRAINT_NAME}"
        )
