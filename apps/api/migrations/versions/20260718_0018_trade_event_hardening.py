"""Generalize Outbox and protect immutable quotation snapshots.

Revision ID: 20260718_0018
Revises: 20260718_0017
"""
from alembic import op
import sqlalchemy as sa

revision = "20260718_0018"
down_revision = "20260718_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("outbox_events") as batch:
        batch.alter_column("decision_id", existing_type=sa.Uuid(as_uuid=True), nullable=True)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE FUNCTION atc_reject_quotation_snapshot_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'quotation snapshots are immutable'; END $$")
        for table in ("quotation_versions", "quotation_items"):
            op.execute(f"CREATE TRIGGER trg_immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION atc_reject_quotation_snapshot_mutation()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("quotation_items", "quotation_versions"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_immutable_{table} ON {table}")
        op.execute("DROP FUNCTION IF EXISTS atc_reject_quotation_snapshot_mutation")
    op.execute("DELETE FROM outbox_events WHERE decision_id IS NULL")
    with op.batch_alter_table("outbox_events") as batch:
        batch.alter_column("decision_id", existing_type=sa.Uuid(as_uuid=True), nullable=False)
