# Implement claim notes system for agents and crews

## Summary

Add a claim notes system so different agents and crews can read and write notes to a claim, enabling cross-crew communication and persistent context as claims move through the workflow.

## Background

Currently there is no dedicated mechanism for agents/crews to share notes on a claim. The only note-like fields are:

- **`review_notes`** – Single adjuster field on the claims table (human-facing, review queue only)
- **`request_info` note** – Stored in audit log when requesting info from claimant (action-specific)
- **Audit log `details`** – Action-specific context, not a general-purpose notes API

Agents and crews have no tools to append or read shared notes, so downstream crews cannot benefit from observations made by earlier crews (e.g., New Claim crew, Fraud crew, Settlement crew).

## Proposed solution

### 1. Database

Add a `claim_notes` table:

```sql
CREATE TABLE claim_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    note TEXT NOT NULL,
    actor_id TEXT NOT NULL,  -- 'workflow', crew name, or agent identifier
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX idx_claim_notes_claim_id ON claim_notes(claim_id);
```

### 2. API

- `GET /api/claims/{claim_id}/notes` – List notes for a claim (ordered by `created_at`)
- `POST /api/claims/{claim_id}/notes` – Add a note. Body: `{ "note": "...", "actor_id": "..." }`

### 3. Agent tools

- **`add_claim_note(claim_id: str, note: str, actor_id: str)`** – Append a note to the claim
- **`get_claim_notes(claim_id: str)`** – Retrieve all notes for the claim (for use by downstream crews)

Expose these tools to crews that need them (e.g., New Claim, Total Loss, Partial Loss, Fraud, Settlement).

### 4. Repository / service layer

- Add `ClaimRepository` methods: `add_note()`, `get_notes()`
- Wire into API routes and tools

## Acceptance criteria

- [ ] `claim_notes` table exists (Alembic migration)
- [ ] GET and POST endpoints for claim notes
- [ ] `add_claim_note` and `get_claim_notes` tools available to crews
- [ ] Notes are returned in claim detail/history where appropriate (optional: include in `GET /api/claims/{id}` response)
- [ ] Unit tests for repository, API, and tools

## Out of scope (for later)

- Note editing/deletion
- Note categories or tags
- Access control per note
