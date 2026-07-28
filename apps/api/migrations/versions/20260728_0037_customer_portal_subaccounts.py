"""Add customer portal subaccounts and their read-only order trail.

Revision ID: 20260728_0037
Revises: 20260726_0036
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260728_0037"
down_revision = "20260726_0036"
branch_labels = None
depends_on = None


U = lambda: sa.Uuid(as_uuid=True)
NOW = sa.text("CURRENT_TIMESTAMP")
PORTAL_PERMISSION_ROWS = (
    (
        "customer_portal.subaccount_manage",
        "customer_portal",
        "subaccount_manage",
        "Create, suspend, and review customer subaccounts",
    ),
    (
        "customer_portal.access",
        "customer_portal",
        "access",
        "Access the customer ordering portal",
    ),
    (
        "customer_portal.order_create",
        "customer_portal",
        "order_create",
        "Create a customer order request from the catalog",
    ),
    (
        "customer_portal.order_view_self",
        "customer_portal",
        "order_view_self",
        "View own customer order requests",
    ),
)


def _audit() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _add_membership_columns() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite cannot add the composite self foreign key without rebuilding
        # the tenant-wide membership table.  The application enforces the
        # same-tenant parent rule locally; preserve the named unique
        # constraint through a batch rebuild so SQLAlchemy metadata remains
        # identical to the PostgreSQL shape used in production.
        with op.batch_alter_table("memberships") as batch:
            batch.add_column(
                sa.Column(
                    "account_scope",
                    sa.String(30),
                    nullable=False,
                    server_default="STAFF",
                )
            )
            batch.add_column(sa.Column("parent_membership_id", U(), nullable=True))
            batch.add_column(sa.Column("login_identifier", sa.String(320), nullable=True))
            batch.create_unique_constraint(
                "uq_memberships_tenant_login_identifier",
                ["tenant_id", "login_identifier"],
            )
            batch.create_index(
                "ix_memberships_tenant_parent_scope",
                ["tenant_id", "parent_membership_id", "account_scope"],
            )
        return

    with op.batch_alter_table("memberships") as batch:
        batch.add_column(
            sa.Column("account_scope", sa.String(30), nullable=False, server_default=sa.text("'STAFF'"))
        )
        batch.add_column(sa.Column("parent_membership_id", U(), nullable=True))
        batch.add_column(sa.Column("login_identifier", sa.String(320), nullable=True))
        batch.create_check_constraint(
            "account_scope_allowed",
            "account_scope IN ('STAFF', 'CUSTOMER_SUBACCOUNT')",
        )
        batch.create_unique_constraint(
            "uq_memberships_tenant_login_identifier",
            ["tenant_id", "login_identifier"],
        )
        batch.create_foreign_key(
            "fk_memberships_tenant_parent_membership",
            "memberships",
            ["tenant_id", "parent_membership_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_memberships_tenant_parent_scope",
            ["tenant_id", "parent_membership_id", "account_scope"],
        )
        batch.alter_column("account_scope", server_default=None)


def _create_supporting_tables() -> None:
    op.create_table(
        "local_account_credentials",
        sa.Column("user_id", U(), nullable=False),
        sa.Column("identifier_normalized", sa.String(320), nullable=False),
        sa.Column("password_salt", sa.String(128), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        *_audit(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_local_account_credentials_user", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_local_account_credentials"),
        sa.UniqueConstraint(
            "identifier_normalized", name="uq_local_account_credentials_identifier"
        ),
    )
    op.create_table(
        "customer_account_access_events",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("membership_id", U(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "event_type IN ('LOGIN', 'ORDER_SUBMITTED')", name="event_type_allowed"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_customer_account_access_events_tenant", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_customer_account_access_events_tenant_membership",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_customer_account_access_events"),
    )
    op.create_index(
        "ix_customer_account_access_events_tenant_membership_occurred",
        "customer_account_access_events",
        ["tenant_id", "membership_id", "occurred_at"],
    )


def _add_quote_submitter() -> None:
    bind = op.get_bind()
    op.add_column(
        "public_quote_drafts",
        sa.Column("submitted_by_membership_id", U(), nullable=True),
    )
    op.create_index(
        "ix_public_quote_drafts_tenant_submitter_created",
        "public_quote_drafts",
        ["tenant_id", "submitted_by_membership_id", "created_at"],
    )
    if bind.dialect.name != "sqlite":
        with op.batch_alter_table("public_quote_drafts") as batch:
            batch.create_foreign_key(
                "fk_public_quote_drafts_tenant_submitter",
                "memberships",
                ["tenant_id", "submitted_by_membership_id"],
                ["tenant_id", "id"],
                ondelete="SET NULL",
            )


def _provision_postgres_roles() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # Existing tenants do not pass through application seeding again. Reconcile
    # the small immutable role set inside the migration while FORCE RLS is
    # temporarily relaxed for the schema owner.
    for table in ("tenants", "roles", "role_permissions"):
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
    try:
        values = ",\n            ".join(
            "(gen_random_uuid(), '{code}', '{module}', '{action}', '{description}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)".format(
                code=code,
                module=module,
                action=action,
                description=description.replace("'", "''"),
            )
            for code, module, action, description in PORTAL_PERMISSION_ROWS
        )
        op.execute(
            f"""
            INSERT INTO public.permissions (
                id, code, module, action, description, created_at, updated_at, deleted_at
            ) VALUES
                {values}
            ON CONFLICT (code) DO UPDATE
            SET module = EXCLUDED.module,
                action = EXCLUDED.action,
                description = EXCLUDED.description,
                deleted_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            """
        )
        op.execute(
            """
            DO $customer_portal$
            DECLARE
                v_tenant_id uuid;
                v_role_id uuid;
                v_staff_role text;
            BEGIN
                FOR v_tenant_id IN
                    SELECT id FROM public.tenants WHERE deleted_at IS NULL
                LOOP
                    INSERT INTO public.roles (
                        id, tenant_id, code, name, description, is_system, status,
                        created_at, updated_at, deleted_at
                    ) VALUES (
                        gen_random_uuid(), v_tenant_id, 'CUSTOMER_SUBACCOUNT',
                        'Customer Subaccount',
                        'Restricted customer ordering portal access.',
                        true, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL
                    )
                    ON CONFLICT (tenant_id, code) DO UPDATE
                    SET name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        is_system = true,
                        status = 'active',
                        deleted_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id INTO v_role_id;

                    INSERT INTO public.role_permissions (
                        id, tenant_id, role_id, permission_id,
                        created_at, updated_at, deleted_at
                    )
                    SELECT gen_random_uuid(), v_tenant_id, v_role_id, permission.id,
                           CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL
                    FROM public.permissions AS permission
                    WHERE permission.code IN (
                        'customer_portal.access',
                        'customer_portal.order_create',
                        'customer_portal.order_view_self'
                    )
                    ON CONFLICT (tenant_id, role_id, permission_id) DO UPDATE
                    SET deleted_at = NULL, updated_at = CURRENT_TIMESTAMP;

                    FOR v_staff_role IN SELECT unnest(ARRAY['OWNER', 'ADMIN'])
                    LOOP
                        SELECT id INTO v_role_id
                        FROM public.roles
                        WHERE tenant_id = v_tenant_id
                          AND code = v_staff_role
                          AND deleted_at IS NULL;
                        IF v_role_id IS NOT NULL THEN
                            INSERT INTO public.role_permissions (
                                id, tenant_id, role_id, permission_id,
                                created_at, updated_at, deleted_at
                            )
                            SELECT gen_random_uuid(), v_tenant_id, v_role_id, permission.id,
                                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL
                            FROM public.permissions AS permission
                            WHERE permission.code = 'customer_portal.subaccount_manage'
                            ON CONFLICT (tenant_id, role_id, permission_id) DO UPDATE
                            SET deleted_at = NULL, updated_at = CURRENT_TIMESTAMP;
                        END IF;
                    END LOOP;
                END LOOP;
            END;
            $customer_portal$
            """
        )
    finally:
        for table in ("role_permissions", "roles", "tenants"):
            op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def _enable_postgres_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute('ALTER TABLE "customer_account_access_events" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "customer_account_access_events" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "customer_account_access_events_tenant_isolation" '
        'ON "customer_account_access_events" FOR ALL '
        f"USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})"
    )


def upgrade() -> None:
    _add_membership_columns()
    _create_supporting_tables()
    _add_quote_submitter()
    _provision_postgres_roles()
    _enable_postgres_rls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            'DROP POLICY IF EXISTS "customer_account_access_events_tenant_isolation" '
            'ON "customer_account_access_events"'
        )
    if op.get_bind().dialect.name != "sqlite":
        with op.batch_alter_table("public_quote_drafts") as batch:
            batch.drop_constraint("fk_public_quote_drafts_tenant_submitter", type_="foreignkey")
    op.drop_index("ix_public_quote_drafts_tenant_submitter_created", table_name="public_quote_drafts")
    op.drop_column("public_quote_drafts", "submitted_by_membership_id")
    op.drop_index(
        "ix_customer_account_access_events_tenant_membership_occurred",
        table_name="customer_account_access_events",
    )
    op.drop_table("customer_account_access_events")
    op.drop_table("local_account_credentials")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("memberships") as batch:
            batch.drop_index("ix_memberships_tenant_parent_scope")
            batch.drop_constraint(
                "uq_memberships_tenant_login_identifier", type_="unique"
            )
            batch.drop_column("login_identifier")
            batch.drop_column("parent_membership_id")
            batch.drop_column("account_scope")
        return
    with op.batch_alter_table("memberships") as batch:
        batch.drop_index("ix_memberships_tenant_parent_scope")
        batch.drop_constraint("fk_memberships_tenant_parent_membership", type_="foreignkey")
        batch.drop_constraint("uq_memberships_tenant_login_identifier", type_="unique")
        batch.drop_constraint("account_scope_allowed", type_="check")
        batch.drop_column("login_identifier")
        batch.drop_column("parent_membership_id")
        batch.drop_column("account_scope")
