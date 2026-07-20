"""Phase 1.5 audit timestamps and soft-delete contract.

Revision ID: 20260718_0002
Revises: 20260718_0001
Requirements: DB-006, DB-IAM-001, DB-IAM-002
"""
from alembic import op
import sqlalchemy as sa


revision = "20260718_0002"
down_revision = "20260718_0001"
branch_labels = None
depends_on = None


PHASE1_TABLES = (
    "organizations",
    "tenants",
    "users",
    "memberships",
    "roles",
    "permissions",
    "role_permissions",
    "membership_roles",
)

NEEDS_UPDATED_AT = ("permissions", "role_permissions", "membership_roles")


def _has_column(table: str, column: str) -> bool:
    if op.get_context().as_sql:
        return False
    return column in {
        item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)
    }


def upgrade() -> None:
    for table in PHASE1_TABLES:
        if not _has_column(table, "deleted_at"):
            op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    for table in NEEDS_UPDATED_AT:
        if not _has_column(table, "updated_at"):
            op.add_column(
                table,
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            )
        op.execute(
            sa.text(f'UPDATE "{table}" SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)')
        )
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                "updated_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
            )
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_email", type_="unique")
        batch_op.alter_column(
            "email",
            new_column_name="email_normalized",
            existing_type=sa.String(320),
            nullable=True,
        )
        batch_op.drop_column("password_hash")
    op.create_index("ix_users_email_normalized", "users", ["email_normalized"], unique=False)
    if op.get_bind().dialect.name == "postgresql":
        _replace_user_visibility_policy(include_soft_delete=True)


def _replace_user_visibility_policy(*, include_soft_delete: bool) -> None:
    tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    user_id = "NULLIF(current_setting('app.current_user_id', true), '')::uuid"
    membership_delete_filter = " AND m.deleted_at IS NULL" if include_soft_delete else ""
    user_visibility = (
        f"id = {user_id} OR EXISTS ("
        "SELECT 1 FROM memberships m "
        f"WHERE m.user_id = users.id AND m.tenant_id = {tenant_id} "
        f"AND m.status = 'active'{membership_delete_filter}"
        ")"
    )
    op.execute('DROP POLICY IF EXISTS "users_tenant_visibility" ON "users"')
    op.execute(
        'CREATE POLICY "users_tenant_visibility" ON "users" '
        f'FOR ALL USING ({user_visibility}) WITH CHECK (id = {user_id})'
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _replace_user_visibility_policy(include_soft_delete=False)
    op.drop_index("ix_users_email_normalized", table_name="users")
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("password_hash", sa.String(255), nullable=True))
        batch_op.alter_column(
            "email_normalized",
            new_column_name="email",
            existing_type=sa.String(320),
            nullable=False,
        )
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_unique_constraint("uq_users_email", ["email"])
    for table in reversed(NEEDS_UPDATED_AT):
        op.drop_column(table, "updated_at")
    for table in reversed(PHASE1_TABLES):
        op.drop_column(table, "deleted_at")
