"""Allow editable pending quote lines while retaining finalized/identity guards."""

from alembic import op

revision = "20260907_0135"
down_revision = "20260906_0134"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # Replace the body atomically; keep the existing trigger and function ACLs.
    # Do not turn off tenant RLS or bypass the calling runtime role's access.
    op.execute("""
        CREATE OR REPLACE FUNCTION public.atc_reject_public_quote_draft_item_mutation()
        RETURNS trigger LANGUAGE plpgsql
        SECURITY INVOKER SET search_path = pg_catalog, public AS $$
        DECLARE
            draft_status text;
            draft_deleted_at timestamptz;
            editable_fields text[] := ARRAY[
                'unit_price_snapshot', 'quantity', 'line_total',
                'name_snapshot', 'description_snapshot', 'specification_snapshot',
                'category_snapshot', 'unit_code_snapshot', 'currency_snapshot',
                'updated_at'
            ];
        BEGIN
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'public quote draft items cannot be deleted'
                    USING ERRCODE = '23514';
            END IF;
            -- Allow only the fields exposed by the pending quote edit/currency
            -- APIs. Identity, SKU provenance, carton rules and soft-deletion
            -- stay protected, including any future columns not in this list.
            IF (to_jsonb(NEW) - editable_fields) IS DISTINCT FROM
               (to_jsonb(OLD) - editable_fields) THEN
                RAISE EXCEPTION 'public quote draft item identity and source fields are immutable'
                    USING ERRCODE = '23514';
            END IF;
            -- Serialize with confirmation on the same parent row. Recheck
            -- the current status after waiting for any concurrent confirmer.
            SELECT status, deleted_at INTO draft_status, draft_deleted_at
            FROM public.public_quote_drafts
            WHERE id = OLD.quote_draft_id AND tenant_id = OLD.tenant_id
            FOR UPDATE;
            IF NOT FOUND OR draft_status IS DISTINCT FROM 'PENDING_CONFIRMATION'
                         OR draft_deleted_at IS NOT NULL THEN
                RAISE EXCEPTION 'only pending public quote draft items may be edited'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
        CREATE OR REPLACE FUNCTION public.atc_reject_public_quote_draft_item_mutation()
        RETURNS trigger LANGUAGE plpgsql
        SECURITY INVOKER SET search_path = pg_catalog, public AS $$
        BEGIN
            RAISE EXCEPTION 'public quote draft item snapshots are immutable';
        END $$
    """)
