"""Add tenant-scoped storefront product-view analytics.

Revision ID: 20260729_0042
Revises: 20260729_0041
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import context, op


revision = "20260729_0042"
down_revision = "20260729_0041"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)


def _enable_tenant_rls(table_name: str, policy_name: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY "{policy_name}" ON "{table_name}" '
        f"FOR ALL USING (tenant_id = {tenant}) "
        f"WITH CHECK (tenant_id = {tenant})"
    )


def _database_uuid() -> object:
    value = uuid4()
    return value if op.get_bind().dialect.name == "postgresql" else value.hex


def _provision_analytics_permission() -> None:
    bind = op.get_bind()
    permission_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'analytics.view'")
    ).scalar_one_or_none()
    if permission_id is None:
        permission_id = _database_uuid()
        bind.execute(
            sa.text(
                """
                INSERT INTO permissions (
                    id, code, module, action, description,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    :id, 'analytics.view', 'analytics', 'view',
                    'View tenant storefront product analytics',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL
                )
                """
            ),
            {"id": permission_id},
        )
    else:
        bind.execute(
            sa.text(
                """
                UPDATE permissions
                SET module = 'analytics',
                    action = 'view',
                    description = 'View tenant storefront product analytics',
                    updated_at = CURRENT_TIMESTAMP,
                    deleted_at = NULL
                WHERE id = :permission_id
                """
            ),
            {"permission_id": permission_id},
        )

    is_postgresql = bind.dialect.name == "postgresql"
    if is_postgresql:
        op.execute('ALTER TABLE "roles" NO FORCE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "role_permissions" NO FORCE ROW LEVEL SECURITY')
    try:
        roles = bind.execute(
            sa.text(
                """
                SELECT id, tenant_id
                FROM roles
                WHERE code IN ('OWNER', 'ADMIN')
                  AND status = 'active'
                  AND deleted_at IS NULL
                """
            )
        ).all()
        for role_id, tenant_id in roles:
            assignment_id = bind.execute(
                sa.text(
                    """
                    SELECT id
                    FROM role_permissions
                    WHERE tenant_id = :tenant_id
                      AND role_id = :role_id
                      AND permission_id = :permission_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "role_id": role_id,
                    "permission_id": permission_id,
                },
            ).scalar_one_or_none()
            if assignment_id is None:
                bind.execute(
                    sa.text(
                        """
                        INSERT INTO role_permissions (
                            id, tenant_id, role_id, permission_id,
                            created_at, updated_at, deleted_at
                        ) VALUES (
                            :id, :tenant_id, :role_id, :permission_id,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL
                        )
                        """
                    ),
                    {
                        "id": _database_uuid(),
                        "tenant_id": tenant_id,
                        "role_id": role_id,
                        "permission_id": permission_id,
                    },
                )
            else:
                bind.execute(
                    sa.text(
                        """
                        UPDATE role_permissions
                        SET updated_at = CURRENT_TIMESTAMP,
                            deleted_at = NULL
                        WHERE id = :assignment_id
                        """
                    ),
                    {"assignment_id": assignment_id},
                )
    finally:
        if is_postgresql:
            op.execute('ALTER TABLE "role_permissions" FORCE ROW LEVEL SECURITY')
            op.execute('ALTER TABLE "roles" FORCE ROW LEVEL SECURITY')


def upgrade() -> None:
    op.create_table(
        "storefront_product_view_events",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("event_id", sa.String(80), nullable=False),
        sa.Column("product_id", U(), nullable=False),
        sa.Column("sku_id", U(), nullable=False),
        sa.Column("sku_code_snapshot", sa.String(160), nullable=False),
        sa.Column("product_name_snapshot", sa.String(500), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(country_code) = 2 AND country_code = upper(country_code)",
            name="ck_storefront_product_view_events_country_code_format",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_storefront_product_view_events_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_storefront_product_view_events_tenant_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_storefront_product_view_events_tenant_sku",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_storefront_product_view_events",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_product_view_events_tenant_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            name="uq_storefront_product_view_events_event",
        ),
    )
    op.create_index(
        "ix_storefront_product_view_events_tenant_occurred",
        "storefront_product_view_events",
        ["tenant_id", "occurred_at"],
    )
    op.create_index(
        "ix_storefront_product_view_events_tenant_sku_occurred",
        "storefront_product_view_events",
        ["tenant_id", "sku_id", "occurred_at"],
    )
    op.create_index(
        "ix_storefront_product_view_events_tenant_country_occurred",
        "storefront_product_view_events",
        ["tenant_id", "country_code", "occurred_at"],
    )

    op.create_table(
        "storefront_product_view_daily",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("viewed_on", sa.Date(), nullable=False),
        sa.Column("product_id", U(), nullable=False),
        sa.Column("sku_id", U(), nullable=False),
        sa.Column("sku_code_snapshot", sa.String(160), nullable=False),
        sa.Column("product_name_snapshot", sa.String(500), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("view_count", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "view_count >= 1",
            name="ck_storefront_product_view_daily_view_count_positive",
        ),
        sa.CheckConstraint(
            "length(country_code) = 2 AND country_code = upper(country_code)",
            name="ck_storefront_product_view_daily_country_code_format",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_storefront_product_view_daily_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_storefront_product_view_daily_tenant_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_storefront_product_view_daily_tenant_sku",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_storefront_product_view_daily",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_product_view_daily_tenant_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "viewed_on",
            "country_code",
            "sku_id",
            name="uq_storefront_product_view_daily_bucket",
        ),
    )
    op.create_index(
        "ix_storefront_product_view_daily_tenant_date",
        "storefront_product_view_daily",
        ["tenant_id", "viewed_on"],
    )
    op.create_index(
        "ix_storefront_product_view_daily_tenant_product_date",
        "storefront_product_view_daily",
        ["tenant_id", "product_id", "viewed_on"],
    )
    op.create_index(
        "ix_storefront_product_view_daily_tenant_country_date",
        "storefront_product_view_daily",
        ["tenant_id", "country_code", "viewed_on"],
    )

    _enable_tenant_rls(
        "storefront_product_view_events",
        "storefront_product_view_events_tenant_isolation",
    )
    _enable_tenant_rls(
        "storefront_product_view_daily",
        "storefront_product_view_daily_tenant_isolation",
    )
    if not context.is_offline_mode():
        _provision_analytics_permission()


def downgrade() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"
    if not context.is_offline_mode():
        if is_postgresql:
            op.execute('ALTER TABLE "role_permissions" NO FORCE ROW LEVEL SECURITY')
        try:
            bind.execute(
                sa.text(
                    """
                    DELETE FROM role_permissions
                    WHERE permission_id IN (
                        SELECT id FROM permissions WHERE code = 'analytics.view'
                    )
                    """
                )
            )
        finally:
            if is_postgresql:
                op.execute('ALTER TABLE "role_permissions" FORCE ROW LEVEL SECURITY')
        bind.execute(
            sa.text("DELETE FROM permissions WHERE code = 'analytics.view'")
        )

    op.drop_index(
        "ix_storefront_product_view_daily_tenant_country_date",
        table_name="storefront_product_view_daily",
    )
    op.drop_index(
        "ix_storefront_product_view_daily_tenant_product_date",
        table_name="storefront_product_view_daily",
    )
    op.drop_index(
        "ix_storefront_product_view_daily_tenant_date",
        table_name="storefront_product_view_daily",
    )
    op.drop_table("storefront_product_view_daily")
    op.drop_index(
        "ix_storefront_product_view_events_tenant_country_occurred",
        table_name="storefront_product_view_events",
    )
    op.drop_index(
        "ix_storefront_product_view_events_tenant_sku_occurred",
        table_name="storefront_product_view_events",
    )
    op.drop_index(
        "ix_storefront_product_view_events_tenant_occurred",
        table_name="storefront_product_view_events",
    )
    op.drop_table("storefront_product_view_events")
