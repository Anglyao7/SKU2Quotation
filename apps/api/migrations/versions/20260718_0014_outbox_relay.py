"""Add durable Outbox Relay leases, retry/dead-letter state and Inbox receipts.

Revision ID: 20260718_0014
Revises: 20260718_0013
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260718_0014"
down_revision = "20260718_0013"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql")


def _uuid() -> sa.types.TypeEngine:
    return sa.Uuid(as_uuid=True)


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _add_relay_columns() -> None:
    op.drop_index("ix_outbox_events_unpublished", table_name="outbox_events")
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.drop_constraint(
            "ck_outbox_events_status_allowed", "outbox_events", type_="check"
        )
        op.drop_constraint(
            "ck_outbox_events_publication_lifecycle_consistent",
            "outbox_events",
            type_="check",
        )
        op.add_column(
            "outbox_events",
            sa.Column(
                "available_at",
                sa.DateTime(timezone=True),
                nullable=True,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.execute("UPDATE outbox_events SET available_at = occurred_at")
        op.alter_column("outbox_events", "available_at", nullable=False)
        for column in (
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("lease_owner", sa.String(120), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        ):
            op.add_column("outbox_events", column)
        op.create_check_constraint(
            "ck_outbox_events_status_allowed",
            "outbox_events",
            "status IN ('PENDING', 'PROCESSING', 'PUBLISHED', 'FAILED', 'DEAD')",
        )
        op.create_check_constraint(
            "ck_outbox_events_max_attempts_positive",
            "outbox_events",
            "max_attempts >= 1",
        )
        op.create_check_constraint(
            "ck_outbox_events_publication_lifecycle_consistent",
            "outbox_events",
            "(status = 'PUBLISHED' AND published_at IS NOT NULL AND dead_lettered_at IS NULL) "
            "OR (status = 'DEAD' AND published_at IS NULL AND dead_lettered_at IS NOT NULL) "
            "OR (status IN ('PENDING', 'PROCESSING', 'FAILED') "
            "AND published_at IS NULL AND dead_lettered_at IS NULL)",
        )
        op.create_check_constraint(
            "ck_outbox_events_lease_lifecycle_consistent",
            "outbox_events",
            "(status = 'PROCESSING' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'PROCESSING' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
        )
    else:
        with op.batch_alter_table("outbox_events", recreate="always") as batch:
            batch.drop_constraint("ck_outbox_events_status_allowed", type_="check")
            batch.drop_constraint(
                "ck_outbox_events_publication_lifecycle_consistent", type_="check"
            )
            batch.add_column(
                sa.Column(
                    "available_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                )
            )
            batch.add_column(
                sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5")
            )
            batch.add_column(sa.Column("lease_owner", sa.String(120), nullable=True))
            batch.add_column(
                sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
            )
            batch.add_column(
                sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True)
            )
            batch.add_column(
                sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True)
            )
            batch.create_check_constraint(
                "ck_outbox_events_status_allowed",
                "status IN ('PENDING', 'PROCESSING', 'PUBLISHED', 'FAILED', 'DEAD')",
            )
            batch.create_check_constraint(
                "ck_outbox_events_max_attempts_positive", "max_attempts >= 1"
            )
            batch.create_check_constraint(
                "ck_outbox_events_publication_lifecycle_consistent",
                "(status = 'PUBLISHED' AND published_at IS NOT NULL AND dead_lettered_at IS NULL) "
                "OR (status = 'DEAD' AND published_at IS NULL AND dead_lettered_at IS NOT NULL) "
                "OR (status IN ('PENDING', 'PROCESSING', 'FAILED') "
                "AND published_at IS NULL AND dead_lettered_at IS NULL)",
            )
            batch.create_check_constraint(
                "ck_outbox_events_lease_lifecycle_consistent",
                "(status = 'PROCESSING' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
                "OR (status <> 'PROCESSING' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            )

    op.create_index(
        "ix_outbox_events_unpublished",
        "outbox_events",
        ["available_at", "id"],
        postgresql_where=sa.text(
            "status IN ('PENDING', 'FAILED') AND dead_lettered_at IS NULL "
            "AND deleted_at IS NULL"
        ),
        sqlite_where=sa.text(
            "status IN ('PENDING', 'FAILED') AND dead_lettered_at IS NULL "
            "AND deleted_at IS NULL"
        ),
    )
    op.create_index(
        "ix_outbox_events_tenant_claim",
        "outbox_events",
        ["tenant_id", "status", "available_at", "lease_expires_at"],
    )


def _create_inbox_events() -> None:
    op.create_table(
        "inbox_events",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("consumer_name", sa.String(120), nullable=False),
        sa.Column("event_id", _uuid(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PROCESSING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", JSON_DOCUMENT, nullable=False),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("last_error_message", sa.String(500), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_inbox_events_attempt_count_nonnegative"
        ),
        sa.CheckConstraint(
            "status IN ('PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_inbox_events_status_allowed",
        ),
        sa.CheckConstraint(
            "(status = 'COMPLETED' AND processed_at IS NOT NULL) "
            "OR (status IN ('PROCESSING', 'FAILED') AND processed_at IS NULL)",
            name="ck_inbox_events_processing_lifecycle_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_inbox_events_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["outbox_events.tenant_id", "outbox_events.id"],
            name="fk_inbox_events_tenant_outbox_event",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_inbox_events"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inbox_events_tenant_identity"),
        sa.UniqueConstraint(
            "tenant_id",
            "consumer_name",
            "event_id",
            name="uq_inbox_events_consumer_event",
        ),
    )
    op.create_index(
        "ix_inbox_events_tenant_status",
        "inbox_events",
        ["tenant_id", "status", "created_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE inbox_events ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE inbox_events FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_isolation ON inbox_events "
            "USING (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid)"
        )


def upgrade() -> None:
    _add_relay_columns()
    _create_inbox_events()


def _drop_relay_columns() -> None:
    op.drop_index("ix_outbox_events_tenant_claim", table_name="outbox_events")
    op.drop_index("ix_outbox_events_unpublished", table_name="outbox_events")
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.drop_constraint(
            "ck_outbox_events_lease_lifecycle_consistent", "outbox_events", type_="check"
        )
        op.drop_constraint(
            "ck_outbox_events_publication_lifecycle_consistent",
            "outbox_events",
            type_="check",
        )
        op.drop_constraint(
            "ck_outbox_events_max_attempts_positive", "outbox_events", type_="check"
        )
        op.drop_constraint(
            "ck_outbox_events_status_allowed", "outbox_events", type_="check"
        )
        op.execute(
            "UPDATE outbox_events SET status='FAILED', published_at=NULL "
            "WHERE status IN ('PROCESSING', 'DEAD')"
        )
        for column in (
            "dead_lettered_at",
            "last_attempt_at",
            "lease_expires_at",
            "lease_owner",
            "max_attempts",
            "available_at",
        ):
            op.drop_column("outbox_events", column)
        op.create_check_constraint(
            "ck_outbox_events_status_allowed",
            "outbox_events",
            "status IN ('PENDING', 'PUBLISHED', 'FAILED')",
        )
        op.create_check_constraint(
            "ck_outbox_events_publication_lifecycle_consistent",
            "outbox_events",
            "(status = 'PUBLISHED' AND published_at IS NOT NULL) "
            "OR (status IN ('PENDING', 'FAILED') AND published_at IS NULL)",
        )
    else:
        with op.batch_alter_table("outbox_events", recreate="always") as batch:
            batch.drop_constraint(
                "ck_outbox_events_lease_lifecycle_consistent", type_="check"
            )
            batch.drop_constraint(
                "ck_outbox_events_publication_lifecycle_consistent", type_="check"
            )
            batch.drop_constraint(
                "ck_outbox_events_max_attempts_positive", type_="check"
            )
            batch.drop_constraint("ck_outbox_events_status_allowed", type_="check")
            batch.drop_column("dead_lettered_at")
            batch.drop_column("last_attempt_at")
            batch.drop_column("lease_expires_at")
            batch.drop_column("lease_owner")
            batch.drop_column("max_attempts")
            batch.drop_column("available_at")
            batch.create_check_constraint(
                "ck_outbox_events_status_allowed",
                "status IN ('PENDING', 'PUBLISHED', 'FAILED', 'PROCESSING', 'DEAD')",
            )
            batch.create_check_constraint(
                "ck_outbox_events_publication_lifecycle_consistent",
                "(status = 'PUBLISHED' AND published_at IS NOT NULL) "
                "OR (status IN ('PENDING', 'FAILED', 'PROCESSING', 'DEAD') "
                "AND published_at IS NULL)",
            )
        op.execute(
            "UPDATE outbox_events SET status='FAILED' WHERE status IN ('PROCESSING', 'DEAD')"
        )
        with op.batch_alter_table("outbox_events", recreate="always") as batch:
            batch.drop_constraint("ck_outbox_events_status_allowed", type_="check")
            batch.drop_constraint(
                "ck_outbox_events_publication_lifecycle_consistent", type_="check"
            )
            batch.create_check_constraint(
                "ck_outbox_events_status_allowed",
                "status IN ('PENDING', 'PUBLISHED', 'FAILED')",
            )
            batch.create_check_constraint(
                "ck_outbox_events_publication_lifecycle_consistent",
                "(status = 'PUBLISHED' AND published_at IS NOT NULL) "
                "OR (status IN ('PENDING', 'FAILED') AND published_at IS NULL)",
            )

    op.create_index(
        "ix_outbox_events_unpublished",
        "outbox_events",
        ["occurred_at", "id"],
        postgresql_where=sa.text(
            "status IN ('PENDING', 'FAILED') AND deleted_at IS NULL"
        ),
        sqlite_where=sa.text("status IN ('PENDING', 'FAILED') AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_inbox_events_tenant_status", table_name="inbox_events")
    op.drop_table("inbox_events")
    _drop_relay_columns()
