# Database Schema

The system supports **SQLite** (default) and **PostgreSQL** for persistent storage of claims, audit logs, and workflow results.

For configuration options, see [Configuration](configuration.md).

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `CLAIMS_DB_PATH` | `data/claims.db` | Path to SQLite database file (ignored when `DATABASE_URL` is set) |
| `DATABASE_URL` | (unset) | PostgreSQL connection URL. When set, the app uses PostgreSQL instead of SQLite. Example: `postgresql://user:pass@host:5432/claims` |
| `READ_REPLICA_DATABASE_URL` | (unset) | Optional PostgreSQL read-replica URL. When set alongside `DATABASE_URL`, read-heavy queries are routed to this replica; all writes still go to the primary. Example: `postgresql://user:pass@replica-host:5432/claims` |
| `DB_POOL_SIZE` | `5` | SQLAlchemy `pool_size` when using PostgreSQL (`ge=1`). Applied to both primary and replica engines. |
| `DB_MAX_OVERFLOW` | `10` | SQLAlchemy `max_overflow` when using PostgreSQL (`ge=0`). Applied to both primary and replica engines. |

## PostgreSQL Setup

When using PostgreSQL:

1. **Run migrations before starting the app**: `alembic upgrade head`. The schema is applied via Alembic only; `init_db()` does not run for PostgreSQL.

2. **Connection pooling**: The app uses SQLAlchemy connection pooling for PostgreSQL. Defaults are `pool_size=5` and `max_overflow=10`; override with `DB_POOL_SIZE` and `DB_MAX_OVERFLOW`.

3. **Scripts**: `investigate_claim.py` and other scripts work with both backends. When `DATABASE_URL` is set, `get_db_path()` returns an empty string; scripts use the default connection.

## Schema Change Process

**Alembic is the source of truth** for schema evolution on databases that are upgraded with `alembic upgrade head` (typical production and PostgreSQL setups).

SQLite also supports **non-Alembic** bootstrap and legacy repair paths in the same codebase; those must stay aligned with migrations:

1. **`alembic/versions/`** – Incremental migrations for existing databases. Add a revision for each schema change (e.g. `alembic revision -m "description"`).

2. **`src/claim_agent/db/database.py` – `SCHEMA_SQL`** – Full `CREATE TABLE IF NOT EXISTS` script for **new** SQLite files when the app calls `init_db()` without having run Alembic. New installs and many tests rely on this.

3. **Same file – `_run_migrations()`** – Best-effort `ALTER TABLE` / `CREATE TABLE` steps for **older** SQLite databases that already existed before the current `SCHEMA_SQL` shape (deployments that never use Alembic on SQLite). This path is not a substitute for Alembic on long-lived DBs when you expect full migration history.

**PostgreSQL:** schema comes from Alembic only (`init_db()` does not apply DDL). New Postgres databases use the combined migration **`023_postgres_full_schema.py`**, which duplicates the logical shape of SQLite with dialect-specific types (`SERIAL`, `TIMESTAMP`, etc.). When you change **`incidents`**, **`claim_links`**, or **`claims.incident_id`**, update both **`src/claim_agent/db/schema_incidents_sqlite.py`** (shared SQLite DDL used by `database.py` and revision **022**) and the matching sections in **`023_postgres_full_schema.py`**.

**When changing the schema:**

- Add an Alembic migration for the change.
- Update `SCHEMA_SQL` (and any shared module it uses, e.g. `schema_incidents_sqlite.py`) so new SQLite installs match.
- For Postgres-only DDL in `023`, update in parallel when the same tables/columns are touched.
- Run migrations on existing DBs; `init_db` will not modify existing table columns in all cases, although `SCHEMA_SQL` may still create new indexes or triggers defined there. All schema changes for existing databases that use Alembic must go through Alembic.

## Schema Overview

```mermaid
erDiagram
    claims ||--o{ claim_audit_log : "has"
    claims ||--o{ workflow_runs : "has"
    claims ||--o{ reserve_history : "has"
    claims ||--o{ claim_payments : "has"
    
    claims {
        text id PK
        text policy_number
        text vin
        int vehicle_year
        text vehicle_make
        text vehicle_model
        text incident_date
        text incident_description
        text damage_description
        real estimated_damage
        text claim_type
        text status
        real payout_amount
        real reserve_amount
        text attachments
        text assignee
        text review_started_at
        text review_notes
        text due_at
        text priority
        text siu_case_id
        text archived_at
        text created_at
        text updated_at
    }
    
    claims ||--o{ task_checkpoints : "has"
    claims ||--o{ claim_parties : "has"
    
    claim_audit_log {
        int id PK
        text claim_id FK
        text action
        text old_status
        text new_status
        text details
        text actor_id
        text before_state
        text after_state
        text created_at
    }
    
    reserve_history {
        int id PK
        text claim_id FK
        real old_amount
        real new_amount
        text reason
        text actor_id
        text created_at
    }
    
    workflow_runs {
        int id PK
        text claim_id FK
        text claim_type
        text router_output
        text workflow_output
        text created_at
    }
    
    task_checkpoints {
        int id PK
        text claim_id FK
        text workflow_run_id
        text stage_key
        text output
        text created_at
    }
    
    claim_parties {
        int id PK
        text claim_id FK
        text party_type
        text name
        text email
        text phone
        text address
        text role
        text consent_status
        text authorization_status
        text created_at
        text updated_at
    }

    claim_party_relationships {
        int id PK
        int from_party_id FK
        int to_party_id FK
        text relationship_type
        text created_at
    }

    claim_parties ||--o{ claim_party_relationships : "from_party"
    claim_parties ||--o{ claim_party_relationships : "to_party"

    claim_payments {
        int id PK
        text claim_id FK
        real amount
        text payee
        text payee_type
        text payment_method
        text check_number
        text status
        text authorized_by
        text issued_at
        text cleared_at
        text voided_at
        text void_reason
        text payee_secondary
        text payee_secondary_type
        text external_ref
        text created_at
        text updated_at
    }
```

## Tables

### claims

Main table storing claim records.

```sql
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
    estimated_damage REAL,
    claim_type TEXT,
    status TEXT DEFAULT 'pending',
    payout_amount REAL,
    reserve_amount REAL,
    attachments TEXT DEFAULT '[]',
    assignee TEXT,
    review_started_at TEXT,
    review_notes TEXT,
    due_at TEXT,
    priority TEXT,
    siu_case_id TEXT,
    archived_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Indexes for search performance
CREATE INDEX IF NOT EXISTS idx_claims_vin ON claims(vin);
CREATE INDEX IF NOT EXISTS idx_claims_incident_date ON claims(incident_date);
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Primary key (e.g., CLM-11EEF959) |
| `policy_number` | TEXT | Insurance policy number |
| `vin` | TEXT | Vehicle identification number |
| `vehicle_year` | INTEGER | Year of vehicle |
| `vehicle_make` | TEXT | Vehicle manufacturer |
| `vehicle_model` | TEXT | Vehicle model |
| `incident_date` | TEXT | Date of incident (YYYY-MM-DD) |
| `incident_description` | TEXT | Description of the incident |
| `damage_description` | TEXT | Description of vehicle damage |
| `estimated_damage` | REAL | Estimated repair cost (optional) |
| `claim_type` | TEXT | Classification (new, duplicate, etc.) |
| `status` | TEXT | Current status |
| `payout_amount` | REAL | Settlement amount (if applicable) |
| `reserve_amount` | REAL | Estimated ultimate cost (reserve) set aside for claim |
| `attachments` | TEXT | JSON array of attachment metadata |
| `assignee` | TEXT | Adjuster/user ID (review queue) |
| `review_started_at` | TEXT | When claim entered needs_review |
| `review_notes` | TEXT | Adjuster notes |
| `due_at` | TEXT | SLA target datetime (ISO) |
| `priority` | TEXT | critical \| high \| medium \| low (from escalation) |
| `siu_case_id` | TEXT | SIU case ID when fraud workflow creates a referral |
| `archived_at` | TEXT | When claim was archived (retention enforcement) |
| `created_at` | TEXT | Creation timestamp |
| `updated_at` | TEXT | Last update timestamp |

### claim_audit_log

Audit trail of all status changes and actions. **No UPDATE** (trigger-enforced). **DELETE** is permitted for gated retention purge after migration `039` (fresh `init_db` omits the legacy delete trigger). Records are otherwise immutable for compliance.

```sql
CREATE TABLE IF NOT EXISTS claim_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    action TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT,
    details TEXT,
    actor_id TEXT DEFAULT 'system',
    before_state TEXT,
    after_state TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);

CREATE INDEX IF NOT EXISTS idx_claim_audit_log_claim_id ON claim_audit_log(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_audit_log_claim_id_action ON claim_audit_log(claim_id, action);
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key |
| `claim_id` | TEXT | Foreign key to claims.id |
| `action` | TEXT | Event type (see Audit Event Types below) |
| `old_status` | TEXT | Previous status (for status_change) |
| `new_status` | TEXT | New status |
| `details` | TEXT | Additional details/notes |
| `actor_id` | TEXT | Who performed the action: `system`, `workflow`, or adjuster ID |
| `before_state` | TEXT | JSON of state before change (status, claim_type, payout_amount) |
| `after_state` | TEXT | JSON of state after change |
| `created_at` | TEXT | Timestamp of action |

#### Audit Event Types

| Event | Description |
|-------|-------------|
| `created` | Claim record created |
| `status_change` | Status, claim_type, or payout_amount changed |
| `approval` | Human approval for continued processing |
| `rejection` | Human rejection with reason |
| `reprocess` | Workflow reprocessed |
| `escalation` | Escalated for HITL |
| `payout_set` | Payout amount set |
| `attachments_updated` | Attachments modified |
| `document_viewed` | Reserved for future document metadata views (chain of custody) |
| `document_downloaded` | Attachment file served via `GET /api/claims/.../attachments/{key}` or portal equivalent; `after_state` JSON: `storage_key`, `channel` (`adjuster_api` \| `portal`) |
| `document_accessed` | Presigned GET URL issued for S3-backed attachments (claim payload attachment URLs, document list/upload responses, process-with-files); `after_state` JSON: `storage_key`, `channel` (`adjuster_api` \| `portal`) |
| `request_info` | Adjuster requested more info from claimant |
| `escalate_to_siu` | Escalated to Special Investigations Unit |
| `siu_case_created` | SIU case created by fraud workflow (automated referral) |
| `assign` | Claim assigned to adjuster |
| `reserve_set` | Reserve amount set (initial or first) |
| `reserve_adjusted` | Reserve amount changed |
| `payment_authorized` | Disbursement row created (`claim_payments`) |
| `payment_issued` | Payment moved from authorized to issued (e.g. check number set) |
| `payment_cleared` | Issued payment marked cleared |
| `payment_voided` | Payment voided (reversal) |

#### Actor Identity

- `system` – System-level actions (e.g. initialization)
- `workflow` – Automated workflow actions (default for `run_claim_workflow`)
- `<adjuster_id>` – Human adjuster when populated from auth context (API)

#### Retention

After migration `049`, `UPDATE` may change only `before_state` and `after_state`; other columns stay immutable via trigger. **Deletes** are blocked until migration `039` (see [GitHub issue #350](https://github.com/csmangum/auto-agent/issues/350)): after that migration, rows may be removed only through the gated CLI `claim-agent audit-log-purge` (never ad hoc SQL in production). Application code may also replace rows when scrubbing JSON (e.g. `details`) while preserving ids.

**Policy template (carrier-defined):**

- **Default:** retain all audit rows indefinitely after claim purge; no automated audit deletion.
- **Optional:** retain audit rows for **M** calendar years after the parent claim reaches `status=purged` and `purged_at` is set, then **export** (cold storage) and optionally **purge** database rows. Configure `AUDIT_LOG_RETENTION_YEARS_AFTER_PURGE`; purge additionally requires `AUDIT_LOG_PURGE_ENABLED=true` and compliance sign-off.

DSAR deletion anonymizes the claim; `claim_audit_log` is controlled by `DSAR_AUDIT_LOG_POLICY` (`preserve` / `redact` / `delete`). Retention purge may scrub audit JSON when `AUDIT_LOG_STATE_REDACTION_ENABLED=true`. Otherwise historical JSON may remain until audit purge or export—another reason some carriers export then purge audit rows after the legal window.

See [PII and retention](pii-and-retention.md#audit-log-retention-issue-350) and migration `002_audit_trail_enhancements` (append-only triggers), `039_allow_claim_audit_log_delete_for_retention` (removes delete trigger).

### reserve_history

Append-only audit of reserve changes. Used for actuarial analysis, compliance, and reserve adequacy tracking. **Append-only**: no UPDATE or DELETE.

```sql
CREATE TABLE IF NOT EXISTS reserve_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    old_amount REAL,
    new_amount REAL NOT NULL,
    reason TEXT DEFAULT '',
    actor_id TEXT DEFAULT 'workflow',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_reserve_history_claim_id ON reserve_history(claim_id);
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key |
| `claim_id` | TEXT | Foreign key to claims.id |
| `old_amount` | REAL | Previous reserve (NULL for initial set) |
| `new_amount` | REAL | New reserve amount |
| `reason` | TEXT | Reason for change |
| `actor_id` | TEXT | Who made the change |
| `created_at` | TEXT | Timestamp |

Actuarial aggregates and IBNR-style exports: see [Actuarial reserve reporting](actuarial-reserve-reporting.md).

### workflow_runs

Preserves output from each workflow execution.

```sql
CREATE TABLE IF NOT EXISTS workflow_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    claim_type TEXT,
    router_output TEXT,
    workflow_output TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key |
| `claim_id` | TEXT | Foreign key to claims.id |
| `claim_type` | TEXT | Classification from router |
| `router_output` | TEXT | Raw output from router crew |
| `workflow_output` | TEXT | Output from workflow crew |
| `created_at` | TEXT | Timestamp of run |

### task_checkpoints

Task-level checkpoints for resumable workflows. Stores output per stage so reprocessing can resume from a specific point.

**Relationship to workflow_runs:** `workflow_run_id` is a logical run identifier (UUID hex string, e.g. `uuid.uuid4().hex`) generated per workflow execution. It is *not* a foreign key to `workflow_runs.id`—those tables track runs independently. `workflow_runs` stores router/workflow output with an autoincrement `id`; `task_checkpoints` groups stage outputs by `workflow_run_id`. When resuming, the orchestrator loads checkpoints for a given `(claim_id, workflow_run_id)` and can skip completed stages.

```sql
CREATE TABLE IF NOT EXISTS task_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    workflow_run_id TEXT NOT NULL,
    stage_key TEXT NOT NULL,
    output TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id),
    UNIQUE(claim_id, workflow_run_id, stage_key)
);
CREATE INDEX IF NOT EXISTS idx_task_checkpoints_claim_run ON task_checkpoints(claim_id, workflow_run_id);
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key |
| `claim_id` | TEXT | Foreign key to claims.id |
| `workflow_run_id` | TEXT | Logical run identifier (UUID hex); groups checkpoints for one execution. Not a FK to workflow_runs.id. |
| `stage_key` | TEXT | Stage identifier (e.g. router, escalation_check, workflow, settlement) |
| `output` | TEXT | Serialized output from that stage |
| `created_at` | TEXT | Timestamp |

### claim_parties

Claim parties (claimant, policyholder, witness, attorney, provider, lienholder). Stores identity and contact info for people involved in a claim. Used for communication routing (e.g., if claimant has attorney, contact attorney) and payment disbursement.

Directed links between parties (attorney representation, lienholder-for-party, etc.) live in **`claim_party_relationships`**, not on `claim_parties`.

```sql
CREATE TABLE IF NOT EXISTS claim_parties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    party_type TEXT NOT NULL,
    name TEXT,
    email TEXT,
    phone TEXT,
    address TEXT,
    role TEXT,
    consent_status TEXT DEFAULT 'pending',
    authorization_status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_parties_claim_id ON claim_parties(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_parties_claim_type ON claim_parties(claim_id, party_type);
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key |
| `claim_id` | TEXT | Foreign key to claims.id |
| `party_type` | TEXT | claimant, policyholder, witness, attorney, provider, lienholder |
| `name` | TEXT | Party name |
| `email` | TEXT | Email for contact |
| `phone` | TEXT | Phone for SMS/contact |
| `address` | TEXT | Address (optional) |
| `role` | TEXT | Role within claim (e.g., driver, passenger, named_insured) |
| `consent_status` | TEXT | pending, granted, revoked |
| `authorization_status` | TEXT | pending, authorized, denied |
| `created_at` | TEXT | Timestamp |
| `updated_at` | TEXT | Last update timestamp |

### claim_party_relationships

Many-to-many-style edges between rows in `claim_parties` on the same claim. Examples: `represented_by` (from represented party to attorney), `lienholder_for`, `witness_for`.

```sql
CREATE TABLE IF NOT EXISTS claim_party_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_party_id INTEGER NOT NULL,
    to_party_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (from_party_id) REFERENCES claim_parties(id) ON DELETE CASCADE,
    FOREIGN KEY (to_party_id) REFERENCES claim_parties(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_claim_party_relationships_from ON claim_party_relationships(from_party_id);
CREATE INDEX IF NOT EXISTS idx_claim_party_relationships_to ON claim_party_relationships(to_party_id);
CREATE INDEX IF NOT EXISTS idx_claim_party_relationships_from_type
    ON claim_party_relationships(from_party_id, relationship_type);
CREATE UNIQUE INDEX IF NOT EXISTS uq_claim_party_relationships_edge
    ON claim_party_relationships(from_party_id, to_party_id, relationship_type);
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key |
| `from_party_id` | INTEGER | FK to claim_parties.id (subject of the relationship) |
| `to_party_id` | INTEGER | FK to claim_parties.id (related party) |
| `relationship_type` | TEXT | e.g. `represented_by`, `lienholder_for`, `witness_for` |
| `created_at` | TEXT | Timestamp |

**Uniqueness:** At most one row per `(from_party_id, to_party_id, relationship_type)` (`uq_claim_party_relationships_edge`).

**Contact routing:** For claimant primary contact, the repository uses the lowest-`id` `represented_by` edge from the claimant party to an attorney (if that attorney has email or phone).

**API:** `POST /api/claims/{claim_id}/party-relationships`, `DELETE /api/claims/{claim_id}/party-relationships/{relationship_id}` ([`src/claim_agent/api/routes/claims.py`](../src/claim_agent/api/routes/claims.py)).

**DSAR / Privacy:** DSAR access exports include `party_relationships` edges for each claim (columns: `id`, `from_party_id`, `to_party_id`, `relationship_type`, `created_at`). Because this table stores only structural metadata (party IDs and relationship type) with **no direct PII**, relationship rows are exported unchanged even after anonymization/deletion — the referenced party rows will have redacted names and contact details but the edges remain intact so the data subject can see structural links such as attorney representation.

### claim_payments

Disbursement ledger for a claim: multiple payments (repair advances, rental, BI to providers, settlement checks, etc.) are modeled as separate rows. **`claims.payout_amount`** remains a summary settlement figure from workflow; detailed issuance uses this table.

**Lifecycle:** `authorized` → `issued` → `cleared`, or `voided` from `authorized` / `issued`. Transitions are enforced in `PaymentRepository` ([`src/claim_agent/db/payment_repository.py`](../src/claim_agent/db/payment_repository.py)).

**Authority:** Creating a row checks per-role dollar limits (`PAYMENT_ADJUSTER_LIMIT`, `PAYMENT_SUPERVISOR_LIMIT`, `PAYMENT_EXECUTIVE_LIMIT`); see [Configuration](configuration.md#disbursements--payment-authority). Actors `workflow` / `system` skip the check when recording automation.

**API:** `POST/GET /api/claims/{claim_id}/payments`, `POST .../payments/{id}/issue`, `/clear`, `/void` ([`src/claim_agent/api/routes/payments.py`](../src/claim_agent/api/routes/payments.py)). Claimant portal exposes a read-only payment list.

**Idempotency:** Optional `external_ref` (e.g. `workflow_settlement:{workflow_run_id}`) is unique per claim when set; duplicate creates return the existing payment id. Concurrent creates with the same ref rely on that uniqueness; `PaymentRepository` treats a unique violation as “return existing id.” Operational note: optional auto-settlement rows (`PAYMENT_AUTO_RECORD_FROM_SETTLEMENT`) overlap with agent `record_claim_payment` calls if both record the same payout—see [Configuration](configuration.md#disbursements--payment-authority).

```sql
CREATE TABLE IF NOT EXISTS claim_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    amount REAL NOT NULL,
    payee TEXT NOT NULL,
    payee_type TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    check_number TEXT,
    status TEXT NOT NULL DEFAULT 'authorized',
    authorized_by TEXT NOT NULL,
    issued_at TEXT,
    cleared_at TEXT,
    voided_at TEXT,
    void_reason TEXT,
    payee_secondary TEXT,
    payee_secondary_type TEXT,
    external_ref TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_payments_claim_id ON claim_payments(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_payments_status ON claim_payments(status);
-- Unique when external_ref is set (see Alembic migration claim_payments external_ref)
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `claim_id` | TEXT | Foreign key to claims.id |
| `amount` | REAL | Payment amount (USD) |
| `payee` | TEXT | Primary payee name |
| `payee_type` | TEXT | claimant, repair_shop, rental_company, medical_provider, lienholder, attorney, other |
| `payment_method` | TEXT | check, ach, wire, card, other |
| `check_number` | TEXT | Set when issuing checks |
| `status` | TEXT | authorized, issued, cleared, voided |
| `authorized_by` | TEXT | Actor who created the row |
| `issued_at` / `cleared_at` / `voided_at` | TEXT | ISO timestamps for lifecycle |
| `void_reason` | TEXT | When status is voided |
| `payee_secondary` / `payee_secondary_type` | TEXT | Two-party check (e.g. lienholder + insured) |
| `external_ref` | TEXT | Optional idempotency key per claim |
| `created_at` / `updated_at` | TEXT | Timestamps |

## Status Constants

Defined in `src/claim_agent/db/constants.py`:

| Constant | Value | Description |
|----------|-------|-------------|
| `STATUS_PENDING` | "pending" | Initial state after creation |
| `STATUS_PROCESSING` | "processing" | Workflow is running |
| `STATUS_OPEN` | "open" | New claim opened |
| `STATUS_CLOSED` | "closed" | Claim finalized (legacy) |
| `STATUS_DUPLICATE` | "duplicate" | Marked as duplicate |
| `STATUS_FRAUD_SUSPECTED` | "fraud_suspected" | Flagged for fraud |
| `STATUS_PARTIAL_LOSS` | "partial_loss" | Reserved for schema/validation |
| `STATUS_SETTLED` | "settled" | Total loss or partial loss settlement complete |
| `STATUS_NEEDS_REVIEW` | "needs_review" | Escalated for HITL |
| `STATUS_PENDING_INFO` | "pending_info" | Awaiting info from claimant |
| `STATUS_FAILED` | "failed" | Processing failed |

## Status Flow

Status transitions are enforced by the [Claim State Machine](state-machine.md). Invalid transitions raise `InvalidClaimTransitionError`.

```mermaid
flowchart TD
    pending["pending (initial)"]
    processing["processing"]
    needs_review["needs_review"]
    failed["failed"]
    success["(success)"]
    open["open (new)"]
    duplicate["duplicate"]
    settled["settled (t.l / p.l / bodily_injury)"]
    fraud["fraud_suspected"]

    pending --> processing
    processing --> needs_review
    processing --> failed
    processing --> success
    success --> open
    success --> duplicate
    success --> settled
    success --> fraud
```

## Repository Operations

The `ClaimRepository` class (`src/claim_agent/db/repository.py`) provides:

- All updates use **parameterized queries** (no string interpolation of user input) to avoid SQL injection.

### create_claim

```python
def create_claim(self, claim_input: ClaimInput) -> str:
    """Insert new claim, generate ID, log 'created' audit entry. Returns claim_id."""
```

- Generates unique claim ID (CLM-XXXXXXXX)
- Inserts claim record with status 'pending'
- Creates audit log entry with action `created`, actor_id (default `workflow`)

### get_claim

```python
def get_claim(self, claim_id: str) -> dict[str, Any] | None:
    """Fetch claim by ID."""
```

- Returns claim as dictionary or None if not found

### update_claim_status

```python
def update_claim_status(
    self,
    claim_id: str,
    new_status: str,
    details: str | None = None,
    claim_type: str | None = None,
    payout_amount: float | None = None,
    *,
    actor_id: str = "workflow",
    skip_validation: bool = False,
    skip_adequacy_check: bool = False,
    role: str = "adjuster",
) -> None:
    """Update status, optionally claim_type and payout_amount; log state change."""
```

- Updates claim status
- **State machine enforced** when `skip_validation=False`: valid transitions only; invalid transitions raise `InvalidClaimTransitionError`. This includes the reserve adequacy gate for moves to `closed` / `settled` when configured ([State machine — reserve gate](state-machine.md#reserve-adequacy-gate-closed--settled)).
- **`skip_validation=True`**: skips all state-machine checks (including the reserve gate). See [State machine — Bypass](state-machine.md#bypass).
- **`skip_adequacy_check`** / **`role`**: when the gate is `block`, supervisor / admin / executive may pass `skip_adequacy_check=True` to allow an inadequate reserve; see [State machine](state-machine.md).
- See [State Machine](state-machine.md) for full transition matrix and guards
- Optionally updates claim_type and payout_amount
- Creates audit log entry with action `status_change`, actor_id, before_state, after_state

### save_workflow_result

```python
def save_workflow_result(
    self,
    claim_id: str,
    claim_type: str,
    router_output: str,
    workflow_output: str,
) -> None:
    """Save workflow run result to workflow_runs."""
```

- Preserves router and workflow outputs
- Allows multiple runs per claim (reprocessing)

### get_claim_history

```python
def get_claim_history(
    self,
    claim_id: str,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Get audit log entries for a claim with optional pagination."""
```

- Returns (rows, total_count). Use limit/offset for pagination on large claims

### search_claims

```python
def search_claims(
    self,
    vin: str | None = None,
    incident_date: str | None = None,
) -> list[dict[str, Any]]:
    """Search claims by VIN and/or incident_date."""
```

- Used for duplicate detection
- Returns matching claims

### create_incident

```python
def create_incident(
    self,
    incident_input: IncidentInput,
    *,
    actor_id: str = ACTOR_SYSTEM,
) -> tuple[str, list[str]]:
    """Create incident and one claim per vehicle. Returns (incident_id, claim_ids)."""
```

Lives in `IncidentRepository` (`src/claim_agent/db/incident_repository.py`).

#### Transaction semantics

All **database writes** — the `incidents` row, every `claims` row (including its
`claim_audit_log` entry, initial reserve, and `claim_parties` rows), and all
`claim_links` — execute inside a **single SQLAlchemy connection context**.  If
any write raises an exception the connection's transaction is rolled back
automatically, leaving no partial rows in the database.

#### Pre-transaction I/O

Policy-adapter lookups (external network calls) are performed **before** the
transaction opens.  This avoids holding the database lock during potentially
slow HTTP calls.  If a lookup fails the corresponding policy data is omitted and
creation continues; no exception is raised for individual lookup failures.

#### Post-transaction best-effort steps

Two operations run **after** the transaction has committed, each in its own
short-lived transaction:

| Step | Failure behaviour |
|------|-------------------|
| Apply UCSPA deadline (`_apply_ucspa_at_fnol`) | `OperationalError` / `ProgrammingError` (e.g. missing UCSPA columns): logged as a warning; processing continues for the remaining claims. Run `alembic upgrade head` to apply the schema. Any **other** exception is logged and **re-raised** (same as `ClaimRepository.create_claim`); the incident and claims are already committed. |
| Emit `claim-submitted` event | Listener failures are logged as a warning; processing continues. If UCSPA raised before emit for a claim, that claim’s event is not sent. |

A process crash or unhandled exception **between the main commit and these
post-transaction steps** will leave the incident and claims persisted but
without UCSPA deadlines set or `claim-submitted` events emitted.  Operators
can recover by re-applying UCSPA deadlines manually or re-emitting events.

#### Deprecated compensating rollback

An older multi-commit code path used `_rollback_incident` as a compensating
"best-effort" cleanup when partial state was left in the database.  That method
is **deprecated** and is no longer called by `create_incident` itself.  It is
retained for any external callers that may reference it directly, but will be
removed in a future release.

#### Future work

The post-transaction steps (UCSPA, events) are candidates for a transactional
outbox or saga pattern so that they are durably committed together with the main
incident/claim data and retried automatically on failure.

## Initialization

Database is automatically initialized on first use. The schema is applied **once per database path** per process; repeated `get_connection()` calls do not re-run the schema script.

```python
from claim_agent.db.database import get_connection

with get_connection() as conn:
    # Schema is created automatically (idempotent)
    # Connection is returned ready to use
    pass
```

## Seeding Historical Data

To load mock claims for duplicate detection testing:

```bash
python scripts/seed_claims_from_mock_db.py
```

This loads claims from `data/mock_db.json` into SQLite.

## Querying via CLI

```bash
# Get claim status
claim-agent status CLM-11EEF959

# Get claim history (audit log)
claim-agent history CLM-11EEF959
```

## Example Audit Log

```json
[
  {
    "id": 1,
    "claim_id": "CLM-11EEF959",
    "action": "created",
    "old_status": null,
    "new_status": "pending",
    "details": "Claim record created",
    "actor_id": "workflow",
    "before_state": null,
    "after_state": "{\"status\": \"pending\", \"claim_type\": null, \"payout_amount\": null}",
    "created_at": "2025-01-28 10:00:00"
  },
  {
    "id": 2,
    "claim_id": "CLM-11EEF959",
    "action": "status_change",
    "old_status": "pending",
    "new_status": "processing",
    "details": null,
    "actor_id": "workflow",
    "before_state": "{\"status\": \"pending\", \"claim_type\": null, \"payout_amount\": null}",
    "after_state": "{\"status\": \"processing\", \"claim_type\": null, \"payout_amount\": null}",
    "created_at": "2025-01-28 10:00:01"
  },
  {
    "id": 3,
    "claim_id": "CLM-11EEF959",
    "action": "status_change",
    "old_status": "processing",
    "new_status": "open",
    "details": "Claim ID: CLM-11EEF959, Status: open, Summary: ...",
    "actor_id": "workflow",
    "before_state": "{\"status\": \"processing\", \"claim_type\": \"new\", \"payout_amount\": null}",
    "after_state": "{\"status\": \"open\", \"claim_type\": \"new\", \"payout_amount\": null}",
    "created_at": "2025-01-28 10:00:15"
  }
]
```

## Backup and Migration

### Backup

```bash
cp data/claims.db data/claims.db.backup
```

### Reset

```bash
rm data/claims.db
# Database will be recreated on next use
```

### Export to JSON

```python
import sqlite3
import json

conn = sqlite3.connect('data/claims.db')
conn.row_factory = sqlite3.Row
claims = [dict(row) for row in conn.execute('SELECT * FROM claims').fetchall()]
with open('claims_export.json', 'w') as f:
    json.dump(claims, f, indent=2)
```

## PostgreSQL High Availability

This section covers infrastructure-level patterns for running the PostgreSQL backend in a highly available, production-grade configuration. All patterns below assume `DATABASE_URL` is already set.

### Read Replicas

The application supports an optional read replica via the `READ_REPLICA_DATABASE_URL` environment variable. When set:

- The application creates a separate SQLAlchemy connection pool pointing to the replica.
- Read-heavy, non-mutating queries (reporting, analytics, audit log access, etc.) should use `get_replica_connection()` instead of `get_connection()`.
- All writes continue to use the primary connection (`get_connection()` / `DATABASE_URL`).
- If `READ_REPLICA_DATABASE_URL` is not set, `get_replica_connection()` transparently falls back to the primary.

**Code example:**

```python
from claim_agent.db.database import get_replica_connection
from sqlalchemy import text

with get_replica_connection() as conn:
    rows = conn.execute(
        text("SELECT id, status, created_at FROM claims ORDER BY created_at DESC LIMIT 100")
    ).fetchall()
```

**Health check**: When `READ_REPLICA_DATABASE_URL` is configured, the `/api/health` endpoint includes a `database_replica` key in the `checks` dict (`"ok"`, `"error"`, or `"skipped"`). The overall health status is determined by the primary database only; a degraded replica does not change the top-level `status` field, but the `database_replica` field signals the issue.

**Routing guidance**: Use `get_replica_connection()` for:

- Claim list / search queries
- Audit log reads
- Reporting and analytics aggregations
- Dashboard data that can tolerate slight replication lag

Do **not** use `get_replica_connection()` for:

- Claim status updates or any write operations
- Immediately-consistent reads after a write (use `get_connection()` there)

**Pool tuning**: `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` apply to both the primary and replica engines. Size your pools based on the total connection budget of each PostgreSQL instance.

---

### Streaming Replication (Built-in PostgreSQL)

PostgreSQL streaming replication is the simplest HA building block. One primary server streams WAL (Write-Ahead Log) records to one or more standbys in near-real time.

**Minimal setup (streaming replication):**

```sql
-- On the primary: create a replication role
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replpass';
```

```ini
# postgresql.conf (primary)
wal_level = replica
max_wal_senders = 5
wal_keep_size = 256MB   # keep enough WAL for lagging standbys
hot_standby = on        # allow read queries on standby
```

```ini
# pg_hba.conf (primary) — allow the standby to connect
host replication replicator <standby-ip>/32 scram-sha-256
```

```bash
# On the standby: create base backup from primary
pg_basebackup -h <primary-host> -U replicator -D /var/lib/postgresql/data -Fp -Xs -P -R
# -R writes postgresql.auto.conf and standby.signal automatically

# Start the standby
pg_ctl start -D /var/lib/postgresql/data
```

Monitor replication lag on the primary:

```sql
SELECT client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn,
       (sent_lsn - replay_lsn) AS replication_lag_bytes
FROM pg_stat_replication;
```

Point `READ_REPLICA_DATABASE_URL` at the standby's connection string. The standby is read-only by design.

---

### Patroni (Automated Failover)

[Patroni](https://github.com/zalando/patroni) is the standard open-source solution for automatic PostgreSQL failover. It uses a distributed configuration store (etcd, Consul, or ZooKeeper) to elect a leader and promote a standby when the primary fails.

**Key concepts:**

| Concept | Details |
|---------|---------|
| Leader election | Patroni holds a distributed lock (TTL ~30 s by default). The node holding the lock is the primary. |
| Automatic failover | When the primary fails to renew its lock, a standby is promoted within ~30–60 seconds. |
| Configuration store | etcd v3 is the most common choice for cloud deployments. |
| HAProxy / VIP | Route application traffic through a load balancer or virtual IP that is aware of the current primary. |

**Minimal `patroni.yml` (per node):**

```yaml
scope: claims-cluster
namespace: /db/
name: pg-node-1

restapi:
  listen: 0.0.0.0:8008
  connect_address: <node-ip>:8008

etcd3:
  hosts: <etcd-ip>:2379

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 30
    maximum_lag_on_failover: 1048576   # 1 MB

  pg_hba:
    - host replication replicator 0.0.0.0/0 scram-sha-256
    - host all all 0.0.0.0/0 scram-sha-256

postgresql:
  listen: 0.0.0.0:5432
  connect_address: <node-ip>:5432
  data_dir: /var/lib/postgresql/data
  authentication:
    replication:
      username: replicator
      password: replpass
    superuser:
      username: postgres
      password: postgrespass
  parameters:
    wal_level: replica
    hot_standby: "on"
    max_wal_senders: 5
```

After Patroni promotes a new primary, update `DATABASE_URL` (or let the VIP/HAProxy handle routing transparently). Tools like **PgBouncer** in front of Patroni provide seamless connection routing without application changes.

---

### Connection Routing with PgBouncer

PgBouncer is a lightweight connection pooler that can sit in front of Patroni and route connections to the current primary automatically (using `pgbouncer-rr` or a Patroni-aware config):

```ini
# pgbouncer.ini
[databases]
claims = host=<vip-or-haproxy> port=5432 dbname=claims
claims_replica = host=<replica-host> port=5432 dbname=claims

[pgbouncer]
pool_mode = transaction
listen_port = 6432
listen_addr = 0.0.0.0
auth_type = scram-sha-256
auth_file = /etc/pgbouncer/userlist.txt
max_client_conn = 200
default_pool_size = 20
```

Set `DATABASE_URL=postgresql://user:pass@pgbouncer-host:6432/claims` and `READ_REPLICA_DATABASE_URL=postgresql://user:pass@pgbouncer-host:6432/claims_replica`.

> **Note:** PgBouncer `transaction` pool mode is incompatible with *long-lived* prepared statements (statements that outlive a single transaction). Either use `session` pool mode or disable client-side prepared-statement caching where your driver uses it.
>
> With **psycopg2** (the synchronous driver used by this project via SQLAlchemy), no client-side prepared-statement cache is enabled by default, and SQLAlchemy does not create long-lived server-side prepared statements in the default configuration. Typically, no extra configuration is needed for PgBouncer `transaction` mode with psycopg2.
>
> When using async PostgreSQL via **asyncpg** (for example `postgresql+asyncpg` with `get_connection_async()`), disable asyncpg's prepared-statement cache behind PgBouncer in `transaction` mode:
>
> ```python
> from sqlalchemy.ext.asyncio import create_async_engine
>
> engine = create_async_engine(
>     url,  # e.g. "postgresql+asyncpg://user:pass@pgbouncer-host:6432/claims"
>     pool_size=...,
>     max_overflow=...,
>     connect_args={"statement_cache_size": 0},
> )
> ```
>
> Or append a query parameter to the URL: `postgresql+asyncpg://user:pass@host:6432/claims?statement_cache_size=0`.
>
> Alternatively, use PgBouncer's `session` pool mode to avoid this restriction entirely.

---

### Failover Procedures

#### Manual failover (promote a standby)

```bash
# On the standby — promote to primary
pg_ctl promote -D /var/lib/postgresql/data

# Verify the new primary
psql -h <new-primary-host> -U postgres -c "SELECT pg_is_in_recovery();"
# Should return: f (false) — meaning it is now a primary
```

Update `DATABASE_URL` to point to the new primary. Old primary should be reconfigured as a standby before rejoining the cluster.

#### Patroni failover / switchover

```bash
# Controlled switchover (zero-downtime planned maintenance)
patronictl -c /etc/patroni.yml switchover claims-cluster

# Emergency failover to a specific node
patronictl -c /etc/patroni.yml failover claims-cluster --master pg-node-1 --candidate pg-node-2

# Cluster status
patronictl -c /etc/patroni.yml list
```

#### Health check integration

The `/api/health` endpoint checks both the primary and replica databases. Integrate it with your load balancer or orchestrator:

```bash
# Example: curl health and check exit code
curl -sf http://localhost:8000/api/health | python3 -c "
import sys, json
r = json.load(sys.stdin)
sys.exit(0 if r.get('status') == 'ok' else 1)
"
```

For Kubernetes, add a liveness/readiness probe:

```yaml
livenessProbe:
  httpGet:
    path: /api/health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 15
readinessProbe:
  httpGet:
    path: /api/health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
```

---

### Multi-Region Deployment

For multi-region HA, combine streaming replication with geographic routing:

1. **Primary region**: runs the Patroni cluster (primary + synchronous standby for zero data loss).
2. **Secondary region**: runs an asynchronous standby used as a read replica.
3. **DNS / global load balancer**: routes write traffic to the primary region VIP; read traffic can be routed to the nearest region.

Set:
```bash
DATABASE_URL=postgresql://user:pass@primary-region-vip:5432/claims
READ_REPLICA_DATABASE_URL=postgresql://user:pass@secondary-region-replica:5432/claims
```

Monitor cross-region replication lag carefully — asynchronous replication means the replica may be seconds to minutes behind during network partitions.

---

### Alembic Migrations in HA Environments

Run migrations as a **separate pre-deploy step** before rolling out new application instances:

```bash
# Disable automatic migrations on startup (recommended for production)
RUN_MIGRATIONS_ON_STARTUP=false

# Run migrations manually before deploy
alembic upgrade head
```

This avoids multiple application replicas racing to run the same migration on startup.

