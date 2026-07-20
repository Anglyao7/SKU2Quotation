"""Add revocable authentication sessions and rotating refresh-token hashes.

Revision ID: 20260718_0012
Revises: 20260718_0011
Requirements: AUTH-001, AUTH-002, AUTH-007, DBSC-006, ACG-005
"""

from alembic import op
import sqlalchemy as sa


revision = "20260718_0012"
down_revision = "20260718_0011"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")


def _uuid() -> sa.Uuid:
    return sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "memberships",
        sa.Column("permission_version", sa.BigInteger(), nullable=False, server_default="1"),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("memberships", "permission_version", server_default=None)

    op.create_table(
        "auth_sessions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("active_membership_id", _uuid(), nullable=True),
        sa.Column("token_family_id", _uuid(), nullable=False),
        sa.Column("rotation_counter", sa.Integer(), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("permission_version", sa.BigInteger(), nullable=False),
        sa.Column("csrf_token_hash", sa.String(64), nullable=False),
        sa.Column("device_label", sa.String(120), nullable=True),
        sa.Column("user_agent_summary", sa.String(300), nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "rotation_counter >= 0", name="ck_auth_sessions_rotation_counter_nonnegative"
        ),
        sa.CheckConstraint(
            "session_version >= 1", name="ck_auth_sessions_session_version_positive"
        ),
        sa.CheckConstraint(
            "permission_version >= 1", name="ck_auth_sessions_permission_version_positive"
        ),
        sa.CheckConstraint(
            "expires_at > issued_at", name="ck_auth_sessions_expiry_after_issue"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_auth_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["active_membership_id"],
            ["memberships.id"],
            name="fk_auth_sessions_active_membership_id_memberships",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("token_family_id", name="uq_auth_sessions_token_family"),
    )
    op.create_index(
        "ix_auth_sessions_user_status",
        "auth_sessions",
        ["user_id", "revoked_at", "expires_at"],
    )
    op.create_index(
        "ix_auth_sessions_membership_status",
        "auth_sessions",
        ["active_membership_id", "revoked_at", "expires_at"],
    )

    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("auth_session_id", _uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("replaced_by_token_id", _uuid(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "sequence_number >= 0",
            name="ck_auth_refresh_tokens_sequence_number_nonnegative",
        ),
        sa.CheckConstraint(
            "expires_at > issued_at",
            name="ck_auth_refresh_tokens_expiry_after_issue",
        ),
        sa.ForeignKeyConstraint(
            ["auth_session_id"],
            ["auth_sessions.id"],
            name="fk_auth_refresh_tokens_auth_session_id_auth_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_token_id"],
            ["auth_refresh_tokens.id"],
            name="fk_auth_refresh_tokens_replaced_by_token_id_auth_refresh_tokens",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_auth_refresh_tokens_hash"),
        sa.UniqueConstraint(
            "auth_session_id",
            "sequence_number",
            name="uq_auth_refresh_tokens_session_sequence",
        ),
    )
    op.create_index(
        "ix_auth_refresh_tokens_session_status",
        "auth_refresh_tokens",
        ["auth_session_id", "revoked_at", "expires_at"],
    )


def downgrade() -> None:
    op.drop_table("auth_refresh_tokens")
    op.drop_table("auth_sessions")
    op.drop_column("memberships", "permission_version")
