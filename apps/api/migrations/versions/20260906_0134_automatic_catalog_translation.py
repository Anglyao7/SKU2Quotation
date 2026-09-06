"""Opt-in automatic translation, transactional change signals and job origin."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260906_0134"
down_revision = "20260906_0133"
branch_labels = depends_on = None

WATCHED_TABLES = ("products", "skus", "public_catalog_offers", "product_categories", "product_category_memberships")
JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql")


def upgrade():
    op.add_column("catalog_translation_jobs", sa.Column("origin", sa.String(20), nullable=False, server_default="MANUAL"))
    op.add_column("catalog_translation_jobs", sa.Column("automatic_scope", JSON_DOCUMENT, nullable=False, server_default=sa.text("'{}'")))
    op.create_table("catalog_translation_changes",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table("catalog_translation_automation",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("target_locale", sa.String(20), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_publish", sa.Boolean(), nullable=False),
        sa.Column("debounce_seconds", sa.Integer(), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("observed_generation", sa.Integer(), nullable=False),
        sa.Column("observed_sources", JSON_DOCUMENT, nullable=False),
        sa.Column("pending_since", sa.DateTime(timezone=True)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_job_id", sa.Uuid()),
        sa.Column("last_error", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        for table in ("catalog_translation_changes", "catalog_translation_automation"):
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" FOR ALL USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})')
        # These are the runtime role names pinned by the managed Compose files.
        # Existing API/worker writes start firing the new trigger at commit,
        # before the separate db-grants container runs. Grant only the trigger's
        # required access in this same transaction, keeping tenant RLS intact.
        # Fresh/single-role development databases need not contain these roles.
        op.execute("""DO $$
        DECLARE runtime_role text;
        BEGIN
          FOR runtime_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('atc_app', 'atc_worker') LOOP
            EXECUTE format('GRANT SELECT, INSERT, UPDATE ON TABLE public.catalog_translation_changes TO %I', runtime_role);
          END LOOP;
        END $$""")
        op.execute("""CREATE FUNCTION atc_catalog_translation_changed() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE target uuid;
        BEGIN
          IF TG_OP = 'DELETE' THEN target := OLD.tenant_id; ELSE target := NEW.tenant_id; END IF;
          IF EXISTS (SELECT 1 FROM tenants WHERE id = target) THEN
            INSERT INTO catalog_translation_changes(tenant_id, generation, changed_at)
            VALUES (target, 1, clock_timestamp())
            ON CONFLICT (tenant_id) DO UPDATE SET generation = catalog_translation_changes.generation + 1, changed_at = EXCLUDED.changed_at;
          END IF;
          RETURN NULL;
        END $$""")
        for table in WATCHED_TABLES:
            op.execute(f'CREATE TRIGGER atc_translation_change AFTER INSERT OR UPDATE OR DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION atc_catalog_translation_changed()')
    else:
        for table in WATCHED_TABLES:
            for action in ("INSERT", "UPDATE", "DELETE"):
                row = "OLD" if action == "DELETE" else "NEW"
                op.execute(f'''CREATE TRIGGER atc_translation_{table}_{action.lower()} AFTER {action} ON "{table}" BEGIN
                  INSERT INTO catalog_translation_changes(tenant_id, generation, changed_at)
                  SELECT {row}.tenant_id, 1, strftime('%Y-%m-%d %H:%M:%f', 'now')
                  WHERE EXISTS (SELECT 1 FROM tenants WHERE id = {row}.tenant_id)
                  ON CONFLICT(tenant_id) DO UPDATE SET generation = generation + 1, changed_at = excluded.changed_at;
                END''')


def downgrade():
    postgres = op.get_bind().dialect.name == "postgresql"
    for table in WATCHED_TABLES:
        if postgres:
            op.execute(f'DROP TRIGGER IF EXISTS atc_translation_change ON "{table}"')
        else:
            for action in ("insert", "update", "delete"):
                op.execute(f'DROP TRIGGER IF EXISTS atc_translation_{table}_{action}')
    if postgres:
        op.execute("DROP FUNCTION IF EXISTS atc_catalog_translation_changed()")
    op.drop_table("catalog_translation_automation")
    op.drop_table("catalog_translation_changes")
    op.drop_column("catalog_translation_jobs", "automatic_scope")
    op.drop_column("catalog_translation_jobs", "origin")
