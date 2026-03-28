# Unified External Portal – Design & Operator Guide

## Context

Before this change the system exposed two parallel external-portal entry points:

| Role | Frontend URL | Backend prefix | Auth header |
|---|---|---|---|
| Claimant | `/portal/login` | `/api/v1/portal/*` | `X-Claim-Access-Token` / policy+VIN / email |
| Repair shop | `/repair-portal/login` | `/api/v1/repair-portal/*` | `X-Repair-Shop-Access-Token` / Bearer JWT |

External parties who needed to access both portals required separate bookmarks,
separate tokens, and separate login flows.

## Decision: Unified entry point with role auto-detection

### Frontend

`/portal/login` is now the **single** login page for all external users. A
role selector at the top of the page lets the user identify themselves as a
**Policyholder** or **Repair Shop**. After successful authentication the page
redirects to the appropriate area of the application.

`/repair-portal/login` (and the bare `/repair-portal`) now **redirect** to
`/portal/login?role=repair_shop` so that existing bookmarks continue to work.

### Backend – `GET /api/v1/portal/auth/role`

A lightweight endpoint that accepts any credential type and returns the
resolved role. The frontend calls this to confirm identity before storing
session state. Accepted credentials:

| Header | Resolved role |
|---|---|
| `X-Portal-Token` | As stored in `external_portal_tokens.role` |
| `X-Repair-Shop-Access-Token` + `X-Claim-Id` | `repair_shop` (legacy) |
| `X-Claim-Access-Token` | `claimant` (legacy) |
| `X-Policy-Number` + `X-Vin` | `claimant` |
| `X-Email` | `claimant` (when `DSAR_VERIFICATION_REQUIRED=false`) |

### Backend – `POST /api/v1/portal/auth/login`

Mirrors `POST /api/v1/repair-portal/auth/login` so the frontend can use a single
login endpoint. Both endpoints remain active during the transition period.
The response now includes a `role` and `redirect` field so the frontend can
route accordingly without probing the token after login.

### Token model – `external_portal_tokens`

A new table stores unified tokens that carry the role explicitly:

```sql
CREATE TABLE external_portal_tokens (
    id        SERIAL PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,   -- SHA-256(raw_token)
    role      TEXT NOT NULL,           -- 'claimant' | 'repair_shop' | 'tpa'
    scopes    TEXT NOT NULL DEFAULT '[]', -- JSON array of permissions
    claim_id  TEXT REFERENCES claims(id), -- required for sessions; NULL not supported for access
    shop_id   TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Legacy tables (`claim_access_tokens`, `repair_shop_access_tokens`,
`third_party_access_tokens`) remain unchanged.

### Scopes

- **Issuance:** `POST /api/v1/portal/auth/issue-token` requires a **non-empty** `scopes`
  array; every value must be in the server’s allowed scope set (see
  `VALID_PORTAL_SCOPES` in code).
- **Verification:** `require_portal_scopes(...)` treats **empty** `scopes` on a unified
  token as **full legacy access** for that role (same as claimant/repair headers without
  fine-grained scopes). Tokens with a non-empty `scopes` list must hold every scope
  required by the route. A warning is logged when a stored unified token has empty
  scopes so operators can migrate to explicit permissions.

## Security considerations

### Timing oracle (informational)

When legacy token headers are presented, the backend validates against the
appropriate table directly based on which header is sent. There is no
cross-table sequential lookup that would leak which table holds a token.

The `GET /api/v1/portal/auth/role` endpoint follows the same pattern: it resolves
the credential using the header(s) present (see the table above) and performs
only the corresponding lookup—not a sequential scan of multiple token tables.

Unified tokens (`X-Portal-Token`) remain the preferred option for new
integrations because they carry the role explicitly and simplify backend logic
and operational policy.

### Token revocation

Unified tokens can be revoked immediately via `revoked_at`:

```python
from claim_agent.services.unified_portal_tokens import revoke_unified_portal_token
revoke_unified_portal_token(raw_token)
```

Legacy tokens expire naturally; there is no revocation endpoint today.

## Issuing tokens per role

### Claimant token

```python
from claim_agent.services.portal_verification import create_claim_access_token

raw = create_claim_access_token("CLM-12345", party_id=7, email="user@example.com")
# Deliver raw token to claimant via email; deep-link:
# https://claims.example.com/portal/login?token=<raw>
```

### Repair-shop per-claim token (legacy)

```python
from claim_agent.services.repair_shop_portal_tokens import create_repair_shop_access_token

raw = create_repair_shop_access_token("CLM-12345", shop_id="SHOP-001")
# Deep-link (recommended): fragment keeps token off the query string:
# https://claims.example.com/portal/login#claim_id=CLM-12345&token=<raw>
# Query-string alternative: /portal/login?role=repair_shop&claim_id=...&token=...
```

### Unified token (recommended for new integrations)

```python
from claim_agent.services.unified_portal_tokens import create_unified_portal_token

# Claimant
raw = create_unified_portal_token(
    "claimant",
    scopes=["read_claim", "upload_doc"],
    claim_id="CLM-12345",
)

# Repair shop
raw = create_unified_portal_token(
    "repair_shop",
    scopes=["read_claim", "update_repair_status"],
    claim_id="CLM-12345",
    shop_id="SHOP-001",
)

# Deliver via X-Portal-Token header or as a deep-link query param:
# https://claims.example.com/portal/login?token=<raw>
```

The `POST /api/v1/portal/auth/issue-token` API endpoint (requires internal
API-key auth) can also be used to mint unified tokens programmatically.

## Deprecation path

| Old URL | Status | New URL |
|---|---|---|
| `GET /repair-portal/login` (frontend) | **Redirects** (302) to `/portal/login?role=repair_shop` | `/portal/login` |
| `POST /api/v1/repair-portal/auth/login` | **Active** (backward compat); schedule removal after one release cycle | `POST /api/v1/portal/auth/login` |
| `/repair-portal/claims/:id` (frontend) | **Active** (no change) | n/a |

The backend route `/api/v1/repair-portal/*` will remain active indefinitely for
existing API integrations; operators who want to enforce the unified entry
point can add a reverse-proxy redirect.

## Environment variables

No new environment variables are required. The new endpoints respect existing
feature flags:

| Flag | Effect |
|---|---|
| `CLAIMANT_PORTAL_ENABLED` | Gates claimant credential paths in unified deps |
| `REPAIR_SHOP_PORTAL_ENABLED` | Gates repair-shop credential paths in `POST /api/v1/portal/auth/login` |
| `JWT_SECRET` | Required for JWT-based shop user login |
