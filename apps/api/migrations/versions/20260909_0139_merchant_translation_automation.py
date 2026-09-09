"""Make automatic catalog translation a merchant-level setting."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260909_0139"
down_revision = "20260908_0138"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "catalog_translation_automation_tenants",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "updated_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    # Preserve existing opt-in language configurations during the migration.
    # A merchant that had at least one enabled language remains enabled once
    # the worker switches to the merchant-level gate.
    op.execute(
        """
        INSERT INTO catalog_translation_automation_tenants
            (tenant_id, enabled, updated_by_user_id, updated_at)
        SELECT a.tenant_id, TRUE,
               (SELECT a2.approved_by_user_id
                  FROM catalog_translation_automation a2
                 WHERE a2.tenant_id = a.tenant_id AND a2.enabled = TRUE
                 LIMIT 1),
               CURRENT_TIMESTAMP
        FROM catalog_translation_automation a
        WHERE a.enabled = TRUE
        GROUP BY a.tenant_id
        """
    )
    if op.get_bind().dialect.name == "postgresql":
        tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        op.execute(
            "ALTER TABLE catalog_translation_automation_tenants ENABLE ROW LEVEL SECURITY"
        )
        op.execute(
            "ALTER TABLE catalog_translation_automation_tenants FORCE ROW LEVEL SECURITY"
        )
        op.execute(
            """
            CREATE POLICY catalog_translation_automation_tenants_tenant_isolation
            ON catalog_translation_automation_tenants FOR ALL
            USING (tenant_id = %s) WITH CHECK (tenant_id = %s)
            """ % (tenant, tenant)
        )
        op.execute(
            """
            DO $$
            DECLARE runtime_role text;
            BEGIN
              FOR runtime_role IN SELECT rolname FROM pg_roles
                WHERE rolname IN ('atc_app', 'atc_worker') LOOP
                EXECUTE format(
                  'GRANT SELECT, INSERT, UPDATE ON TABLE public.catalog_translation_automation_tenants TO %I',
                  runtime_role
                );
              END LOOP;
            END $$
            """
        )


def downgrade():
    op.drop_table("catalog_translation_automation_tenants")
