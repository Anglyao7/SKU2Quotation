"""Add scheduled storefront announcements and their management permission.

Revision ID: 20260730_0043
Revises: 20260729_0042
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql


revision = "20260730_0043"
down_revision = "20260729_0042"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)
JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def _database_uuid() -> object:
    value = uuid4()
    return value if op.get_bind().dialect.name == "postgresql" else value.hex


def _enable_tenant_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute('ALTER TABLE "storefront_announcements" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "storefront_announcements" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "storefront_announcements_tenant_isolation" '
        'ON "storefront_announcements" '
        f"FOR ALL USING (tenant_id = {tenant}) "
        f"WITH CHECK (tenant_id = {tenant})"
    )


def _provision_permission() -> None:
    bind = op.get_bind()
    permission_id = bind.execute(
        sa.text(
            "SELECT id FROM permissions WHERE code = 'announcement.manage'"
        )
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
                    :id, 'announcement.manage', 'announcement', 'manage',
                    'Create, schedule, publish, and remove storefront announcements',
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
                SET module = 'announcement',
                    action = 'manage',
                    description = 'Create, schedule, publish, and remove storefront announcements',
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
                WHERE code IN ('OWNER', 'ADMIN', 'SALES')
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
        "storefront_announcements",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("display_type", sa.String(20), nullable=False),
        sa.Column("ticker_text", sa.Text(), nullable=True),
        sa.Column(
            "content_blocks",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "repeat_interval_hours",
            sa.Integer(),
            nullable=False,
            server_default="24",
        ),
        sa.Column(
            "publication_status",
            sa.String(20),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_by_user_id", U(), nullable=True),
        sa.Column("updated_by_user_id", U(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "display_type IN ('TICKER', 'MODAL')",
            name="ck_storefront_announcements_display_type_allowed",
        ),
        sa.CheckConstraint(
            "publication_status IN ('DRAFT', 'PUBLISHED', 'PAUSED')",
            name="ck_storefront_announcements_publication_status_allowed",
        ),
        sa.CheckConstraint(
            "ends_at > starts_at",
            name="ck_storefront_announcements_schedule_range_valid",
        ),
        sa.CheckConstraint(
            "repeat_interval_hours BETWEEN 1 AND 720",
            name="ck_storefront_announcements_repeat_interval_hours_valid",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_storefront_announcements_version_positive",
        ),
        sa.CheckConstraint(
            "(display_type = 'TICKER' AND ticker_text IS NOT NULL) "
            "OR (display_type = 'MODAL' AND ticker_text IS NULL)",
            name="ck_storefront_announcements_display_content_matches_type",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_storefront_announcements_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_storefront_announcements_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_storefront_announcements_updated_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_storefront_announcements",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_announcements_tenant_identity",
        ),
    )
    op.create_index(
        "ix_storefront_announcements_tenant_schedule",
        "storefront_announcements",
        ["tenant_id", "publication_status", "starts_at", "ends_at"],
    )
    _enable_tenant_rls()
    if not context.is_offline_mode():
        _provision_permission()


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
                        SELECT id FROM permissions
                        WHERE code = 'announcement.manage'
                    )
                    """
                )
            )
        finally:
            if is_postgresql:
                op.execute('ALTER TABLE "role_permissions" FORCE ROW LEVEL SECURITY')
        bind.execute(
            sa.text(
                "DELETE FROM permissions WHERE code = 'announcement.manage'"
            )
        )
    op.drop_index(
        "ix_storefront_announcements_tenant_schedule",
        table_name="storefront_announcements",
    )
    op.drop_table("storefront_announcements")
