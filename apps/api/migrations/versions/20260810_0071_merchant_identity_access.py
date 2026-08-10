"""Add merchant identities with inherited or custom module access.

Revision ID: 20260810_0071
Revises: 20260810_0070
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql


revision = "20260810_0071"
down_revision = "20260810_0070"
branch_labels = None
depends_on = None


JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)

DEFAULT_MODULES = [
    "products",
    "analytics",
    "inventory",
    "announcements",
    "support",
    "support_ai",
    "inquiries",
    "quotations",
    "subaccounts",
]


def _module_list(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return list(DEFAULT_MODULES)
    if not isinstance(value, (list, tuple)):
        return list(DEFAULT_MODULES)
    selected = {str(item) for item in value}
    return [code for code in DEFAULT_MODULES if code in selected]


def upgrade() -> None:
    op.create_table(
        "merchant_identity_profiles",
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("default_modules", JSON_DOCUMENT, nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "code IN ('ADMIN', 'USER')",
            name="ck_merchant_identity_profiles_code_allowed",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_merchant_identity_profiles_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_merchant_identity_profiles_updated_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "code",
            name="pk_merchant_identity_profiles",
        ),
    )
    profiles = sa.table(
        "merchant_identity_profiles",
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("default_modules", JSON_DOCUMENT),
        sa.column("version", sa.BigInteger()),
    )
    profile_rows = [
        {
            "code": "ADMIN",
            "name": "管理员",
            "default_modules": DEFAULT_MODULES,
            "version": 1,
        },
        {
            "code": "USER",
            "name": "用户",
            "default_modules": DEFAULT_MODULES,
            "version": 1,
        },
    ]
    if context.is_offline_mode():
        modules_json = json.dumps(
            DEFAULT_MODULES,
            ensure_ascii=False,
        ).replace("'", "''")
        op.execute(
            "INSERT INTO merchant_identity_profiles "
            "(code, name, default_modules, version) VALUES "
            f"('ADMIN', '管理员', '{modules_json}'::jsonb, 1), "
            f"('USER', '用户', '{modules_json}'::jsonb, 1)"
        )
    else:
        op.get_bind().execute(profiles.insert(), profile_rows)

    op.add_column(
        "tenants",
        sa.Column(
            "identity_code",
            sa.String(length=20),
            nullable=False,
            server_default="USER",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "module_access_mode",
            sa.String(length=20),
            nullable=False,
            server_default="INHERIT",
        ),
    )
    op.create_index(
        "ix_tenants_identity_module_access",
        "tenants",
        ["identity_code", "module_access_mode"],
        unique=False,
    )
    if op.get_bind().dialect.name != "sqlite":
        op.create_check_constraint(
            "module_access_mode_allowed",
            "tenants",
            "module_access_mode IN ('INHERIT', 'CUSTOM')",
        )
        op.create_foreign_key(
            "fk_tenants_identity_code_merchant_identity_profiles",
            "tenants",
            "merchant_identity_profiles",
            ["identity_code"],
            ["code"],
            ondelete="RESTRICT",
        )

    # Alembic's offline SQL renderer has no database result set to inspect.
    # Fresh installations already receive the correct USER/INHERIT defaults;
    # the data-aware compatibility backfill is only needed during an online
    # upgrade of an existing database.
    if context.is_offline_mode():
        return

    bind = op.get_bind()
    protected_tables = ("tenants", "memberships", "users")
    if bind.dialect.name == "postgresql":
        for table_name in protected_tables:
            op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
    try:
        administrator_tenants = {
            str(row[0])
            for row in bind.execute(
                sa.text(
                    """
                    SELECT DISTINCT memberships.tenant_id
                    FROM memberships
                    JOIN users ON users.id = memberships.user_id
                    WHERE users.is_platform_admin = TRUE
                      AND memberships.deleted_at IS NULL
                      AND memberships.status <> 'removed'
                    """
                )
            ).all()
        }
        tenants = bind.execute(
            sa.text("SELECT id, enabled_modules FROM tenants")
        ).mappings().all()
        for tenant in tenants:
            modules = _module_list(tenant["enabled_modules"])
            bind.execute(
                sa.text(
                    """
                    UPDATE tenants
                    SET identity_code = :identity_code,
                        module_access_mode = :module_access_mode
                    WHERE id = :tenant_id
                    """
                ),
                {
                    "tenant_id": tenant["id"],
                    "identity_code": (
                        "ADMIN"
                        if str(tenant["id"]) in administrator_tenants
                        else "USER"
                    ),
                    "module_access_mode": (
                        "INHERIT" if modules == DEFAULT_MODULES else "CUSTOM"
                    ),
                },
            )
    finally:
        if bind.dialect.name == "postgresql":
            for table_name in protected_tables:
                op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "fk_tenants_identity_code_merchant_identity_profiles",
            "tenants",
            type_="foreignkey",
        )
        op.drop_constraint(
            "module_access_mode_allowed",
            "tenants",
            type_="check",
        )
    op.drop_index("ix_tenants_identity_module_access", table_name="tenants")
    op.drop_column("tenants", "module_access_mode")
    op.drop_column("tenants", "identity_code")
    op.drop_table("merchant_identity_profiles")
