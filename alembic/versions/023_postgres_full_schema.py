"""PostgreSQL full schema. Runs only when dialect is postgresql.

For new PostgreSQL deployments, creates all tables in one migration.
SQLite uses migrations 001-022; this no-ops for SQLite.
"""
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    op.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id TEXT PRIMARY KEY,
            incident_date TEXT NOT NULL,
            incident_description TEXT,
            loss_state TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_incidents_incident_date ON incidents(incident_date)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            id TEXT PRIMARY KEY,
            policy_number TEXT NOT NULL,
            vin TEXT NOT NULL,
            vehicle_year INTEGER,
            vehicle_make TEXT,
            vehicle_model TEXT,
            incident_date TEXT,
            incident_description TEXT,
            damage_description TEXT,
            estimated_damage DOUBLE PRECISION,
            claim_type TEXT,
            loss_state TEXT,
            status TEXT DEFAULT 'pending',
            payout_amount DOUBLE PRECISION,
            reserve_amount DOUBLE PRECISION,
            attachments TEXT DEFAULT '[]',
            assignee TEXT,
            review_started_at TEXT,
            review_notes TEXT,
            due_at TEXT,
            priority TEXT,
            siu_case_id TEXT,
            archived_at TEXT,
            incident_id TEXT REFERENCES incidents(id),
            total_loss_metadata TEXT,
            liability_percentage DOUBLE PRECISION,
            liability_basis TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claims_vin ON claims(vin)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claims_incident_date ON claims(incident_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claims_incident_id ON claims(incident_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS claim_links (
            id SERIAL PRIMARY KEY,
            claim_id_a TEXT NOT NULL REFERENCES claims(id),
            claim_id_b TEXT NOT NULL REFERENCES claims(id),
            link_type TEXT NOT NULL,
            opposing_carrier TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (claim_id_a, claim_id_b, link_type)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_links_claim_a ON claim_links(claim_id_a)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_links_claim_b ON claim_links(claim_id_b)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS claim_audit_log (
            id SERIAL PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            action TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT,
            details TEXT,
            actor_id TEXT DEFAULT 'system',
            before_state TEXT,
            after_state TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_audit_log_claim_id ON claim_audit_log(claim_id)")

    op.execute("""
        CREATE OR REPLACE FUNCTION claim_audit_log_prevent_update()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'claim_audit_log is append-only: updates are not allowed';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS claim_audit_log_prevent_update ON claim_audit_log;
        CREATE TRIGGER claim_audit_log_prevent_update
        BEFORE UPDATE ON claim_audit_log FOR EACH ROW EXECUTE PROCEDURE claim_audit_log_prevent_update()
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION claim_audit_log_prevent_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'claim_audit_log is append-only: deletes are not allowed';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS claim_audit_log_prevent_delete ON claim_audit_log;
        CREATE TRIGGER claim_audit_log_prevent_delete
        BEFORE DELETE ON claim_audit_log FOR EACH ROW EXECUTE PROCEDURE claim_audit_log_prevent_delete()
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id SERIAL PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            claim_type TEXT,
            router_output TEXT,
            workflow_output TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS task_checkpoints (
            id SERIAL PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            workflow_run_id TEXT NOT NULL,
            stage_key TEXT NOT NULL,
            output TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(claim_id, workflow_run_id, stage_key)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_task_checkpoints_claim_run ON task_checkpoints(claim_id, workflow_run_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS claim_notes (
            id SERIAL PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            note TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_notes_claim_id ON claim_notes(claim_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS follow_up_messages (
            id SERIAL PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            user_type TEXT NOT NULL,
            message_content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            response_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            responded_at TIMESTAMP,
            actor_id TEXT DEFAULT 'workflow'
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_follow_up_messages_claim_id ON follow_up_messages(claim_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_follow_up_messages_status ON follow_up_messages(claim_id, status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS reserve_history (
            id SERIAL PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            old_amount DOUBLE PRECISION,
            new_amount DOUBLE PRECISION NOT NULL,
            reason TEXT DEFAULT '',
            actor_id TEXT DEFAULT 'workflow',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_reserve_history_claim_id ON reserve_history(claim_id)")
    op.execute("""
        CREATE OR REPLACE FUNCTION reserve_history_prevent_update()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'reserve_history is append-only: updates are not allowed';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS reserve_history_prevent_update ON reserve_history;
        CREATE TRIGGER reserve_history_prevent_update
        BEFORE UPDATE ON reserve_history FOR EACH ROW EXECUTE PROCEDURE reserve_history_prevent_update()
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION reserve_history_prevent_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'reserve_history is append-only: deletes are not allowed';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS reserve_history_prevent_delete ON reserve_history;
        CREATE TRIGGER reserve_history_prevent_delete
        BEFORE DELETE ON reserve_history FOR EACH ROW EXECUTE PROCEDURE reserve_history_prevent_delete()
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS document_requests (
            id SERIAL PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            document_type TEXT NOT NULL,
            requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            requested_from TEXT,
            status TEXT NOT NULL DEFAULT 'requested',
            received_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_document_requests_claim_id ON document_requests(claim_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS claim_tasks (
            id SERIAL PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            title TEXT NOT NULL,
            task_type TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            priority TEXT NOT NULL DEFAULT 'medium',
            assigned_to TEXT,
            created_by TEXT NOT NULL DEFAULT 'workflow',
            due_date TEXT,
            resolution_notes TEXT,
            document_request_id INTEGER REFERENCES document_requests(id),
            recurrence_rule TEXT,
            recurrence_interval INTEGER,
            parent_task_id INTEGER REFERENCES claim_tasks(id),
            escalation_level INTEGER NOT NULL DEFAULT 0,
            escalation_notified_at TEXT,
            escalation_escalated_at TEXT,
            auto_created_from TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_tasks_claim_id ON claim_tasks(claim_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_tasks_status ON claim_tasks(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_tasks_claim_status ON claim_tasks(claim_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_tasks_due_date ON claim_tasks(due_date) WHERE due_date IS NOT NULL AND status NOT IN ('completed', 'cancelled')")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_tasks_parent_task ON claim_tasks(parent_task_id) WHERE parent_task_id IS NOT NULL")

    op.execute("""
        CREATE TABLE IF NOT EXISTS claim_documents (
            id SERIAL PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            storage_key TEXT NOT NULL,
            document_type TEXT,
            received_date TEXT,
            received_from TEXT,
            review_status TEXT NOT NULL DEFAULT 'pending',
            privileged INTEGER NOT NULL DEFAULT 0,
            retention_date TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            extracted_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_id ON claim_documents(claim_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_type ON claim_documents(claim_id, document_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_review ON claim_documents(claim_id, review_status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS claim_payments (
            id SERIAL PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            amount DOUBLE PRECISION NOT NULL,
            payee TEXT NOT NULL,
            payee_type TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            check_number TEXT,
            status TEXT NOT NULL DEFAULT 'authorized',
            authorized_by TEXT NOT NULL,
            issued_at TIMESTAMP,
            cleared_at TIMESTAMP,
            voided_at TIMESTAMP,
            void_reason TEXT,
            payee_secondary TEXT,
            payee_secondary_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_payments_claim_id ON claim_payments(claim_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_payments_status ON claim_payments(status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS claim_parties (
            id SERIAL PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            party_type TEXT NOT NULL,
            name TEXT,
            email TEXT,
            phone TEXT,
            address TEXT,
            role TEXT,
            represented_by_id INTEGER REFERENCES claim_parties(id),
            consent_status TEXT DEFAULT 'pending',
            authorization_status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_parties_claim_id ON claim_parties(claim_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_parties_claim_type ON claim_parties(claim_id, party_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_parties_address_lower ON claim_parties(lower(trim(address)))")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_parties_provider_name ON claim_parties(party_type, lower(trim(name)))")

    op.execute("""
        CREATE TABLE IF NOT EXISTS subrogation_cases (
            id SERIAL PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            case_id TEXT NOT NULL UNIQUE,
            amount_sought DOUBLE PRECISION NOT NULL,
            opposing_carrier TEXT,
            status TEXT DEFAULT 'pending',
            arbitration_status TEXT,
            arbitration_forum TEXT,
            dispute_date TEXT,
            liability_percentage DOUBLE PRECISION,
            liability_basis TEXT,
            recovery_amount DOUBLE PRECISION,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_subrogation_cases_claim_id ON subrogation_cases(claim_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS repair_status (
            id SERIAL PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            shop_id TEXT NOT NULL,
            authorization_id TEXT,
            status TEXT NOT NULL,
            status_updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            paused_at TEXT,
            pause_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_repair_status_claim_id ON repair_status(claim_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_repair_status_shop_status ON repair_status(shop_id, status)")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    # Drop in reverse order of creation (respect FKs)
    for table in [
        "repair_status", "subrogation_cases", "claim_parties", "claim_payments",
        "claim_documents", "claim_tasks", "document_requests", "reserve_history",
        "follow_up_messages", "claim_notes", "task_checkpoints", "workflow_runs",
        "claim_audit_log", "claim_links", "claims", "incidents",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
