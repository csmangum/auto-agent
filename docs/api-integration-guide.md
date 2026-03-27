# API Integration Guide

This guide covers everything an external system needs to integrate with the Claims System REST API: authentication, common end-to-end flows, and request/response reference.

> **Interactive docs** — when the server is running, browse `/api/v1/openapi/docs` (Swagger UI) or `/api/v1/openapi/redoc` for the full OpenAPI spec.  An API key is required when auth is enabled (see [Authentication](#authentication)).

---

## Table of Contents

1. [Base URL and Environments](#base-url-and-environments)
2. [Authentication](#authentication)
   - [API Key](#1-api-key)
   - [JWT (email/password)](#2-jwt-emailpassword)
   - [Portal Tokens](#3-portal-tokens)
3. [Common Flows](#common-flows)
   - [Submit a Claim](#flow-1-submit-a-claim)
   - [Poll Claim Status](#flow-2-poll-claim-status)
   - [Human Review (Approve / Reject)](#flow-3-human-review-approve--reject)
   - [Authorize a Payment](#flow-4-authorize-a-payment)
   - [Claimant Portal](#flow-5-claimant-portal)
   - [Repair Shop Webhooks](#flow-6-repair-shop-webhooks)
   - [ERP Webhooks](#flow-7-erp-webhooks)
   - [DSAR (Privacy Requests)](#flow-8-dsar-privacy-requests)
4. [Error Handling](#error-handling)
5. [Request Limits](#request-limits)
6. [Outbound Webhooks](#outbound-webhooks)

---

## Base URL and Environments

All endpoints share the prefix `/api/v1`. Replace `BASE_URL` throughout this guide with your deployment root:

| Environment | Example Base URL |
|---|---|
| Local development | `http://localhost:8000/api/v1` |
| Staging | `https://claims-staging.example.com/api/v1` |
| Production | `https://claims.example.com/api/v1` |

Legacy `/api/*` paths are permanently redirected (HTTP 308) to the `/api/v1` equivalents.

---

## Authentication

The API supports three authentication methods. All authenticated requests must supply credentials via HTTP headers.

### 1. API Key

The simplest method. Suitable for server-to-server integrations.

**Configuration (server side):**
```bash
# Single key (treated as admin role)
CLAIMS_API_KEY=your-secret-key

# Or multiple keys with explicit roles
API_KEYS=key-adjuster:adjuster,key-supervisor:supervisor:user-42
```

**Request header** — either form is accepted:
```
X-API-Key: your-secret-key
```
```
Authorization: Bearer your-secret-key
```

**Example:**
```bash
curl -s https://claims.example.com/api/v1/claims \
  -H "X-API-Key: your-secret-key"
```

### 2. JWT (email/password)

Use when the calling system has a user credential. Returns short-lived access tokens and a rotation-based refresh token.

#### Login

```bash
curl -s -X POST https://claims.example.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "adjuster@example.com",
    "password": "s3cr3t"
  }'
```

**Response:**
```json
{
  "access_token": "<JWT>",
  "refresh_token": "<opaque-token>",
  "token_type": "bearer",
  "expires_in": 900
}
```

Use the `access_token` in subsequent requests:
```
Authorization: Bearer <JWT>
```

#### Refresh

Access tokens expire after `JWT_ACCESS_TTL_SECONDS` (default 900 s). Refresh before expiry:

```bash
curl -s -X POST https://claims.example.com/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<opaque-token>"}'
```

Response has the same shape as login. The previous refresh token is invalidated; store the new one.

#### Identify the Caller

```bash
curl -s https://claims.example.com/api/v1/auth/me \
  -H "Authorization: Bearer <JWT>"
```

```json
{"identity": "user-42", "role": "adjuster"}
```

**RBAC roles:** `adjuster` · `supervisor` · `admin` · `executive`

### 3. Portal Tokens

Claim-scoped tokens for external parties who must not hold full API credentials.

| Portal | Header | Who issues it |
|---|---|---|
| Claimant | `X-Claim-Access-Token` | Claims system (via `POST /portal/auth/issue-token`) |
| Repair shop (per-claim) | `X-Repair-Shop-Access-Token` | Claims system |
| Third party | `X-Third-Party-Access-Token` | Claims system |
| Unified | `X-Portal-Token` | `POST /portal/auth/login` |

Alternatively, claimants can authenticate without a token using policy/VIN identity headers:
```
X-Claim-Id: CLM-11EEF959
X-Policy-Number: POL-001
X-Vin: 1HGBH41JXMN109186
```

---

## Common Flows

### Flow 1: Submit a Claim

Endpoint: `POST /api/v1/claims`  
Required role: `adjuster` or higher

**Minimum required fields:**

| Field | Type | Description |
|---|---|---|
| `policy_number` | string | Policyholder's policy number |
| `vin` | string | Vehicle identification number |
| `vehicle_year` | integer | Model year |
| `vehicle_make` | string | Manufacturer (e.g. `"Toyota"`) |
| `vehicle_model` | string | Model name (e.g. `"Camry"`) |
| `incident_date` | date (YYYY-MM-DD) | Date loss occurred |
| `incident_description` | string | What happened |
| `damage_description` | string | What was damaged |

**Optional fields:**

| Field | Type | Description |
|---|---|---|
| `estimated_damage` | float | Estimated repair cost in USD |
| `claim_type` | string | Skip router classification when type is already known |
| `loss_state` | string | State/jurisdiction of loss (for UCSPA compliance) |
| `incident_location` | string | Human-readable location |
| `incident_latitude` / `incident_longitude` | float | WGS84 coordinates (both or neither) |
| `attachments` | array | Photos, PDFs, or estimates (see below) |
| `parties` | array | Third parties involved |
| `incident_id` | string | Parent incident ID for multi-vehicle incidents |

**Attachment object:**
```json
{
  "url": "https://storage.example.com/photo.jpg",
  "type": "photo",
  "description": "Front bumper damage"
}
```
Valid `type` values: `photo` · `pdf` · `estimate` · `other`

**Synchronous submission (default):**
```bash
curl -s -X POST https://claims.example.com/api/v1/claims \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "policy_number": "POL-001",
    "vin": "1HGBH41JXMN109186",
    "vehicle_year": 2022,
    "vehicle_make": "Honda",
    "vehicle_model": "Accord",
    "incident_date": "2025-03-15",
    "incident_description": "Rear-ended at a stoplight on Main St.",
    "damage_description": "Rear bumper cracked, trunk lid misaligned.",
    "estimated_damage": 3200.00,
    "loss_state": "CA",
    "attachments": [
      {
        "url": "https://storage.example.com/CLM-001/rear_damage.jpg",
        "type": "photo",
        "description": "Rear bumper"
      }
    ]
  }'
```

**Response (synchronous):**
```json
{
  "claim_id": "CLM-11EEF959",
  "claim_type": "partial_loss",
  "status": "open",
  "actions_taken": [
    "Policy verified",
    "Damage assessed",
    "Repair shop assigned"
  ],
  "payout_amount": 3050.00,
  "liability_percentage": 100.0,
  "reserve_amount": 3500.00,
  "message": "Claim processed successfully."
}
```

**Asynchronous submission** — returns immediately with the claim ID; processing continues in the background:
```bash
curl -s -X POST "https://claims.example.com/api/v1/claims?async=true" \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{ ... }'
```

```json
{
  "claim_id": "CLM-11EEF959",
  "claim_type": null,
  "status": "pending",
  "actions_taken": [],
  "message": "Claim queued for processing."
}
```

Poll `/api/v1/claims/{claim_id}` until `status` is no longer `"pending"` or `"processing"` (see [Flow 2](#flow-2-poll-claim-status)).

---

### Flow 2: Poll Claim Status

Endpoint: `GET /api/v1/claims/{claim_id}`  
Required role: `adjuster` or higher

```bash
curl -s https://claims.example.com/api/v1/claims/CLM-11EEF959 \
  -H "X-API-Key: your-secret-key"
```

**Key response fields:**

| Field | Type | Description |
|---|---|---|
| `id` | string | Claim identifier |
| `status` | string | Current status (see table below) |
| `claim_type` | string | Classified claim type |
| `payout_amount` | float \| null | Authorized payout in USD |
| `reserve_amount` | float \| null | Reserving amount |
| `liability_percentage` | float \| null | 0–100 |
| `created_at` | ISO 8601 | Submission time |
| `updated_at` | ISO 8601 | Last update time |

**Claim status values:**

| Status | Meaning |
|---|---|
| `pending` | Submitted; awaiting processing |
| `processing` | Workflow in progress |
| `open` | Claim opened for claimant |
| `needs_review` | Escalated — awaiting adjuster decision |
| `pending_info` | Additional information requested from claimant |
| `closed` | Claim resolved |
| `settled` | Settlement authorized |
| `denied` | Rejected by adjuster |
| `partial_loss` | Classified as partial loss |
| `fraud_suspected` | Fraud indicators detected |
| `under_investigation` | Escalated to SIU |
| `disputed` | Claimant filed a dispute |
| `dispute_resolved` | Dispute workflow completed |
| `duplicate` | Determined to be a duplicate |
| `failed` | Workflow failed |
| `archived` | Archived for retention |
| `purged` | Purged per retention policy |

**List and filter claims:**
```bash
# Open claims, sorted by creation time
curl -s "https://claims.example.com/api/v1/claims?status=open&sort_by=created_at&sort_order=desc&limit=50" \
  -H "X-API-Key: your-secret-key"
```

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `status` | string | — | Filter by status value |
| `claim_type` | string | — | Filter by claim type |
| `search` | string | — | Free-text search across claim ID, policy number, VIN (max 200 chars) |
| `sort_by` | string | `created_at` | `created_at` · `updated_at` · `incident_date` · `estimated_damage` · `payout_amount` · `status` · `claim_type` · `policy_number` |
| `sort_order` | string | `desc` | `asc` · `desc` |
| `limit` | integer | 100 | 1–1000 |
| `offset` | integer | 0 | Pagination offset |
| `include_archived` | boolean | false | Include archived claims |

---

### Flow 3: Human Review (Approve / Reject)

Claims with fraud indicators, high value, or low-confidence routing are placed in `needs_review`. An adjuster or supervisor must then approve, reject, or request more information.

**Check the review queue:**
```bash
curl -s "https://claims.example.com/api/v1/claims/review-queue" \
  -H "X-API-Key: supervisor-key"
```

#### Approve

Required role: `supervisor` or higher

```bash
curl -s -X POST https://claims.example.com/api/v1/claims/CLM-11EEF959/review/approve \
  -H "X-API-Key: supervisor-key" \
  -H "Content-Type: application/json" \
  -d '{
    "reviewer_decision": {
      "confirmed_claim_type": "partial_loss",
      "confirmed_payout": 3050.00,
      "notes": "Verified repair estimate with body shop."
    }
  }'
```

All fields in `reviewer_decision` are optional; omit the body entirely to approve with the system's recommendation.

#### Reject

```bash
curl -s -X POST https://claims.example.com/api/v1/claims/CLM-11EEF959/review/reject \
  -H "X-API-Key: supervisor-key" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Policy lapsed before incident date."}'
```

**Response:**
```json
{"claim_id": "CLM-11EEF959", "status": "denied"}
```

#### Request More Information

```bash
curl -s -X POST https://claims.example.com/api/v1/claims/CLM-11EEF959/review/request-info \
  -H "X-API-Key: supervisor-key" \
  -H "Content-Type: application/json" \
  -d '{"note": "Please provide a second repair estimate."}'
```

**Response:**
```json
{"claim_id": "CLM-11EEF959", "status": "pending_info"}
```

---

### Flow 4: Authorize a Payment

Payments move through a lifecycle: `authorized` → `issued` → `cleared` (or `voided`).

#### Create an authorized payment

Required role: `adjuster` or higher

```bash
curl -s -X POST https://claims.example.com/api/v1/claims/CLM-11EEF959/payments \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "claim_id": "CLM-11EEF959",
    "amount": 3050.00,
    "payee": "Sunrise Auto Body",
    "payee_type": "repair_shop",
    "payment_method": "ach",
    "external_ref": "INV-2025-0042"
  }'
```

**`payee_type` values:** `claimant` · `repair_shop` · `rental_company` · `medical_provider` · `lienholder` · `attorney` · `other`  
**`payment_method` values:** `check` · `ach` · `wire` · `card` · `other`  
**`external_ref`** is an optional idempotency key (max 200 chars) to prevent duplicate disbursements.

**Response:**
```json
{
  "id": 17,
  "claim_id": "CLM-11EEF959",
  "amount": 3050.00,
  "payee": "Sunrise Auto Body",
  "payee_type": "repair_shop",
  "payment_method": "ach",
  "status": "authorized",
  "authorized_by": "adjuster@example.com",
  "check_number": null,
  "issued_at": null,
  "cleared_at": null,
  "voided_at": null,
  "external_ref": "INV-2025-0042",
  "created_at": "2025-03-16T10:00:00Z",
  "updated_at": "2025-03-16T10:00:00Z"
}
```

#### Issue a payment

```bash
curl -s -X POST https://claims.example.com/api/v1/payments/17/issue \
  -H "X-API-Key: your-secret-key"
```

#### List payments for a claim

```bash
curl -s "https://claims.example.com/api/v1/claims/CLM-11EEF959/payments?status=authorized" \
  -H "X-API-Key: your-secret-key"
```

---

### Flow 5: Claimant Portal

The claimant portal uses claim-scoped tokens (or identity headers) instead of system API keys, limiting access to a single claim.

#### Step 1 — Authenticate

```bash
curl -s -X POST https://claims.example.com/api/v1/portal/auth/issue-token \
  -H "Content-Type: application/json" \
  -d '{
    "claim_id": "CLM-11EEF959",
    "policy_number": "POL-001",
    "vin": "1HGBH41JXMN109186"
  }'
```

Returns a `portal_token` that expires after inactivity (default 30 days).

#### Step 2 — Fetch claim details

```bash
curl -s https://claims.example.com/api/v1/portal/claims/CLM-11EEF959 \
  -H "X-Claim-Access-Token: <portal_token>"
```

#### Step 3 — Upload a document

```bash
curl -s -X POST \
  "https://claims.example.com/api/v1/portal/claims/CLM-11EEF959/documents?document_type=estimate" \
  -H "X-Claim-Access-Token: <portal_token>" \
  -F "file=@/path/to/repair_estimate.pdf"
```

Allowed extensions: `pdf` · `jpg` · `jpeg` · `png` · `gif` · `webp` · `heic` · `doc` · `docx` · `xls` · `xlsx`

**Response:**
```json
{
  "claim_id": "CLM-11EEF959",
  "document_id": 5,
  "document": {
    "id": 5,
    "claim_id": "CLM-11EEF959",
    "document_type": "estimate",
    "url": "https://storage.example.com/CLM-11EEF959/estimate.pdf",
    "received_from": "claimant_portal",
    "review_status": null,
    "created_at": "2025-03-16T11:00:00Z",
    "updated_at": "2025-03-16T11:00:00Z"
  }
}
```

#### Step 4 — File a dispute

```bash
curl -s -X POST https://claims.example.com/api/v1/portal/claims/CLM-11EEF959/dispute \
  -H "X-Claim-Access-Token: <portal_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "dispute_type": "valuation_disagreement",
    "dispute_description": "The ACV valuation is lower than comparable vehicles in my area.",
    "policyholder_evidence": "Attached three comparable listings from AutoTrader."
  }'
```

**`dispute_type` values:** `liability_determination` · `valuation_disagreement` · `repair_estimate` · `deductible_application`

---

### Flow 6: Repair Shop Webhooks

Repair shops push status updates to the claims system as work progresses.

**Endpoint:** `POST /api/v1/webhooks/repair-status`

If `WEBHOOK_SECRET` is configured on the server, include an HMAC-SHA256 signature (see [Signature Verification](#signature-verification)).

```bash
curl -s -X POST https://claims.example.com/api/v1/webhooks/repair-status \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Signature: sha256=<hex_digest>" \
  -d '{
    "claim_id": "CLM-11EEF959",
    "shop_id": "SHOP-042",
    "authorization_id": "AUTH-2025-017",
    "status": "parts_ordered",
    "notes": "OEM bumper on backorder, expected 5 business days."
  }'
```

**Valid `status` values:**

| Value | Meaning |
|---|---|
| `received` | Vehicle accepted at shop |
| `disassembly` | Teardown in progress |
| `parts_ordered` | Parts on order |
| `repair` | Active repair |
| `paint` | In paint booth |
| `reassembly` | Reassembly in progress |
| `qa` | Quality inspection |
| `ready` | Vehicle ready for pickup |
| `paused_supplement` | Repair paused pending supplement approval |

**Response:**
```json
{"ok": true, "repair_status_id": 88}
```

---

### Flow 7: ERP Webhooks

Enterprise repair systems send structured business events through the ERP webhook.

**Endpoint:** `POST /api/v1/webhooks/erp`

#### Estimate approved

```bash
curl -s -X POST https://claims.example.com/api/v1/webhooks/erp \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Signature: sha256=<hex_digest>" \
  -d '{
    "event_type": "estimate_approved",
    "claim_id": "CLM-11EEF959",
    "shop_id": "SHOP-042",
    "erp_event_id": "ERP-EVT-00123",
    "occurred_at": "2025-03-16T09:30:00Z",
    "authorization_id": "AUTH-2025-017",
    "approved_amount": 3050.00
  }'
```

#### Parts delayed

```bash
curl -s -X POST https://claims.example.com/api/v1/webhooks/erp \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "parts_delayed",
    "claim_id": "CLM-11EEF959",
    "shop_id": "SHOP-042",
    "erp_event_id": "ERP-EVT-00124",
    "occurred_at": "2025-03-17T14:00:00Z",
    "delay_reason": "OEM bumper discontinued; sourcing aftermarket.",
    "expected_availability_date": "2025-03-22"
  }'
```

#### Supplement requested

```bash
curl -s -X POST https://claims.example.com/api/v1/webhooks/erp \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "supplement_requested",
    "claim_id": "CLM-11EEF959",
    "shop_id": "SHOP-042",
    "erp_event_id": "ERP-EVT-00125",
    "occurred_at": "2025-03-18T11:00:00Z",
    "supplement_amount": 420.00,
    "description": "Hidden damage to frame rail discovered during teardown."
  }'
```

**Valid `event_type` values:** `estimate_approved` · `parts_delayed` · `supplement_requested`

**`erp_event_id`** is an idempotency key — duplicate events with the same ID are accepted but not re-processed; the response includes `"already_processed": true`.

**Success response:**
```json
{
  "ok": true,
  "event_type": "estimate_approved",
  "claim_id": "CLM-11EEF959",
  "erp_event_id": "ERP-EVT-00123"
}
```

---

### Flow 8: DSAR (Privacy Requests)

Submit GDPR/CCPA data subject access or deletion requests.

#### Access request (right to know)

```bash
curl -s -X POST https://claims.example.com/api/v1/dsar/access \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "claimant_email": "jane.smith@example.com",
    "claim_id": "CLM-11EEF959"
  }'
```

#### Deletion request (right to be forgotten)

```bash
curl -s -X POST https://claims.example.com/api/v1/dsar/deletion \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "claimant_email": "jane.smith@example.com",
    "claim_id": "CLM-11EEF959"
  }'
```

#### Check request status

```bash
curl -s https://claims.example.com/api/v1/dsar/requests/<request_id> \
  -H "X-API-Key: your-secret-key"
```

---

## Error Handling

All error responses share a consistent schema:

```json
{
  "error_code": "CLAIM_NOT_FOUND",
  "detail": "Claim CLM-XXXX does not exist.",
  "details": {
    "claim_id": "CLM-XXXX"
  }
}
```

| Field | Type | Description |
|---|---|---|
| `error_code` | string | Machine-readable identifier (e.g. `CLAIM_NOT_FOUND`, `VALIDATION_ERROR`) |
| `detail` | string \| array | Human-readable message or array of validation errors for 422 responses |
| `details` | object \| null | Structured context (e.g. state transition info) |

**HTTP status codes:**

| Code | Meaning | Common cause |
|---|---|---|
| `200` | OK | Successful read |
| `201` | Created | Resource created |
| `400` | Bad Request | Malformed request or business rule violation |
| `401` | Unauthorized | Missing or invalid credentials |
| `403` | Forbidden | Authenticated but insufficient role |
| `404` | Not Found | Resource does not exist |
| `409` | Conflict | State conflict (e.g. claim already processing) |
| `413` | Payload Too Large | File or body exceeds configured size limit |
| `422` | Unprocessable Entity | Input validation failure; `detail` is an array of field errors |
| `503` | Service Unavailable | Feature disabled or capacity exceeded |

**Validation error detail (422):**
```json
{
  "error_code": "VALIDATION_ERROR",
  "detail": [
    {
      "loc": ["body", "incident_date"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

**Retry guidance:**

- `401` / `403` — fix credentials or request a token refresh before retrying.
- `409` / `503` — back off and retry (exponential backoff recommended).
- `5xx` — transient server errors; retry with backoff up to 3 times.
- `4xx` (other) — do not retry; fix the request.

---

## Request Limits

| Limit | Default | Env var |
|---|---|---|
| General request body | 10 MB | `MAX_REQUEST_BODY_SIZE_MB` |
| File upload body | 100 MB | `MAX_UPLOAD_BODY_SIZE_MB` |
| `Content-Length` required | Yes (POST/PUT/PATCH under `/api`) | — |
| Claim list page size | 1–1000 | (`limit` query param) |
| Search query length | 200 chars | — |

---

## Outbound Webhooks

The system delivers asynchronous events to external URLs as claim state changes.

**Configuration:**
```bash
WEBHOOK_URL=https://your-system.example.com/hooks/claims
# Or multiple destinations:
WEBHOOK_URLS=https://crm.example.com/hook,https://erp.example.com/hook
WEBHOOK_SECRET=your-shared-secret
WEBHOOK_MAX_RETRIES=5
```

### Claim lifecycle events

```json
{
  "event": "claim.needs_review",
  "claim_id": "CLM-11EEF959",
  "status": "needs_review",
  "claim_type": "partial_loss",
  "timestamp": "2025-03-16T10:05:00Z",
  "summary": "Escalated due to high damage estimate."
}
```

**Event types:** `claim.submitted` · `claim.processing` · `claim.needs_review` · `claim.failed` · `claim.opened` · `claim.closed` · `claim.denied` · `claim.pending_info` · `claim.under_investigation` · `claim.archived`

### Repair authorized event

```json
{
  "event": "repair.authorized",
  "claim_id": "CLM-11EEF959",
  "shop_id": "SHOP-042",
  "shop_name": "Sunrise Auto Body",
  "shop_phone": "555-0100",
  "authorized_amount": 3050.00,
  "authorization_id": "AUTH-2025-017",
  "timestamp": "2025-03-16T10:10:00Z"
}
```

### UCSPA deadline approaching

```json
{
  "event": "ucspa.deadline_approaching",
  "claim_id": "CLM-11EEF959",
  "deadline_type": "acknowledgment",
  "due_date": "2025-03-19",
  "loss_state": "CA",
  "timestamp": "2025-03-16T00:00:00Z"
}
```

### Signature Verification

When `WEBHOOK_SECRET` is set, both inbound and outbound webhook requests carry:
```
X-Webhook-Signature: sha256=<hex_digest>
```

**Python verification example:**
```python
import hmac, hashlib

def verify_signature(secret: str, body: bytes, header: str) -> bool:
    expected = hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    received = header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)
```

**Node.js verification example:**
```js
const crypto = require("crypto");

function verifySignature(secret, body, header) {
  const expected = crypto
    .createHmac("sha256", secret)
    .update(body)
    .digest("hex");
  const received = header.replace(/^sha256=/, "");
  return crypto.timingSafeEqual(
    Buffer.from(expected),
    Buffer.from(received)
  );
}
```

Failed verification returns `HTTP 401`. Always validate signatures in production to prevent spoofed events.

---

## See Also

- **[Configuration](configuration.md)** — All environment variables including auth, webhooks, and adapters
- **[Webhooks](webhooks.md)** — Full outbound webhook reference
- **[Adapters](adapters.md)** — Pluggable backends for policy, valuation, repair shops, and SIU
- **[Compliance API](compliance-api.md)** — Fraud reporting and UCSPA deadline endpoints
- **[Actuarial Reserve Reporting](actuarial-reserve-reporting.md)** — Reserve report endpoints (supervisor/admin)
- **[PII and Retention](pii-and-retention.md)** — DSAR, data retention, and right-to-erasure workflows
- **[Adjuster Workflow](adjuster-workflow.md)** — Full review queue and escalation guide
