"""Add storefront support widget, conversations, and support permissions.

Revision ID: 20260803_0052
Revises: 20260802_0051
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql


revision = "20260803_0052"
down_revision = "20260802_0051"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)
JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


PERMISSIONS = (
    (
        "support.view",
        "view",
        "View storefront customer-service conversations",
        ("OWNER", "ADMIN", "SALES"),
    ),
    (
        "support.reply",
        "reply",
        "Reply to and close storefront customer-service conversations",
        ("OWNER", "ADMIN", "SALES"),
    ),
    (
        "support.settings_manage",
        "settings_manage",
        "Manage storefront support floating actions and welcome content",
        ("OWNER", "ADMIN"),
    ),
)


def _database_uuid() -> object:
    value = uuid4()
    return value if op.get_bind().dialect.name == "postgresql" else value.hex


def _enable_rls(table_name: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY "{table_name}_tenant_isolation" '
        f'ON "{table_name}" FOR ALL '
        f"USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})"
    )


def _provision_permissions() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"
    if is_postgresql:
        op.execute('ALTER TABLE "roles" NO FORCE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "role_permissions" NO FORCE ROW LEVEL SECURITY')
    try:
        for code, action, description, role_codes in PERMISSIONS:
            permission_id = bind.execute(
                sa.text("SELECT id FROM permissions WHERE code = :code"),
                {"code": code},
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
                            :id, :code, 'support', :action, :description,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL
                        )
                        """
                    ),
                    {
                        "id": permission_id,
                        "code": code,
                        "action": action,
                        "description": description,
                    },
                )
            else:
                bind.execute(
                    sa.text(
                        """
                        UPDATE permissions
                        SET module = 'support', action = :action,
                            description = :description,
                            updated_at = CURRENT_TIMESTAMP, deleted_at = NULL
                        WHERE id = :permission_id
                        """
                    ),
                    {
                        "permission_id": permission_id,
                        "action": action,
                        "description": description,
                    },
                )
            roles = bind.execute(
                sa.text(
                    """
                    SELECT id, tenant_id FROM roles
                    WHERE code IN :role_codes
                      AND status = 'active' AND deleted_at IS NULL
                    """
                ).bindparams(sa.bindparam("role_codes", expanding=True)),
                {"role_codes": list(role_codes)},
            ).all()
            for role_id, tenant_id in roles:
                assignment = bind.execute(
                    sa.text(
                        """
                        SELECT id FROM role_permissions
                        WHERE tenant_id = :tenant_id AND role_id = :role_id
                          AND permission_id = :permission_id
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "role_id": role_id,
                        "permission_id": permission_id,
                    },
                ).scalar_one_or_none()
                if assignment is None:
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
                            SET updated_at = CURRENT_TIMESTAMP, deleted_at = NULL
                            WHERE id = :assignment
                            """
                        ),
                        {"assignment": assignment},
                    )
    finally:
        if is_postgresql:
            op.execute('ALTER TABLE "role_permissions" FORCE ROW LEVEL SECURITY')
            op.execute('ALTER TABLE "roles" FORCE ROW LEVEL SECURITY')


def upgrade() -> None:
    op.add_column(
        "tenant_public_profiles",
        sa.Column(
            "support_widget_config",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.create_table(
        "storefront_chat_conversations",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("reference_number", sa.String(40), nullable=False),
        sa.Column("visitor_token_hash", sa.String(64), nullable=False),
        sa.Column("visitor_name", sa.String(120), nullable=True),
        sa.Column("visitor_email", sa.String(320), nullable=True),
        sa.Column("locale", sa.String(20), nullable=False, server_default="zh-CN"),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("merchant_last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_visitor_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_merchant_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CLOSED')",
            name="ck_storefront_chat_conversations_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_storefront_chat_conversations_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_storefront_chat_conversations"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_chat_conversations_tenant_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "reference_number",
            name="uq_storefront_chat_conversations_reference",
        ),
        sa.UniqueConstraint(
            "visitor_token_hash",
            name="uq_storefront_chat_conversations_visitor_token",
        ),
    )
    op.create_index(
        "ix_storefront_chat_conversations_tenant_activity",
        "storefront_chat_conversations",
        ["tenant_id", "status", "last_message_at"],
    )
    op.create_table(
        "storefront_chat_messages",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("conversation_id", U(), nullable=False),
        sa.Column("sender_type", sa.String(20), nullable=False),
        sa.Column("sender_user_id", U(), nullable=True),
        sa.Column("client_message_id", sa.String(80), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "sender_type IN ('VISITOR', 'MERCHANT', 'SYSTEM', 'AI')",
            name="ck_storefront_chat_messages_sender_type_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_storefront_chat_messages_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sender_user_id"],
            ["users.id"],
            name="fk_storefront_chat_messages_sender_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["storefront_chat_conversations.tenant_id", "storefront_chat_conversations.id"],
            name="fk_storefront_chat_messages_tenant_conversation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_storefront_chat_messages"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_chat_messages_tenant_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "client_message_id",
            name="uq_storefront_chat_messages_client_identity",
        ),
    )
    op.create_index(
        "ix_storefront_chat_messages_conversation_created",
        "storefront_chat_messages",
        ["tenant_id", "conversation_id", "created_at"],
    )
    _enable_rls("storefront_chat_conversations")
    _enable_rls("storefront_chat_messages")
    if not context.is_offline_mode():
        _provision_permissions()


def downgrade() -> None:
    if not context.is_offline_mode():
        bind = op.get_bind()
        is_postgresql = bind.dialect.name == "postgresql"
        if is_postgresql:
            op.execute('ALTER TABLE "role_permissions" NO FORCE ROW LEVEL SECURITY')
        try:
            bind.execute(
                sa.text(
                    """
                    DELETE FROM role_permissions
                    WHERE permission_id IN (
                        SELECT id FROM permissions WHERE module = 'support'
                    )
                    """
                )
            )
            bind.execute(
                sa.text(
                    "DELETE FROM permissions WHERE code IN "
                    "('support.view', 'support.reply', 'support.settings_manage')"
                )
            )
        finally:
            if is_postgresql:
                op.execute('ALTER TABLE "role_permissions" FORCE ROW LEVEL SECURITY')
    op.drop_index(
        "ix_storefront_chat_messages_conversation_created",
        table_name="storefront_chat_messages",
    )
    op.drop_table("storefront_chat_messages")
    op.drop_index(
        "ix_storefront_chat_conversations_tenant_activity",
        table_name="storefront_chat_conversations",
    )
    op.drop_table("storefront_chat_conversations")
    op.drop_column("tenant_public_profiles", "support_widget_config")
