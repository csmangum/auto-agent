# Compliance REST API

Adjuster-facing endpoints for regulatory and filing visibility. Requires API authentication and an adjuster-capable role where noted.

## Fraud reporting

**`GET /api/compliance/fraud-reporting`**

**Roles:** `adjuster`, `supervisor`, `admin`, or `executive` (see `RequireAdjuster` in the route).

**Query parameters**

| Parameter | Description |
|-----------|-------------|
| `state` | Optional. Filter by loss state (canonical name or two-letter code, e.g. `California` or `CA`). Invalid values return `422`. |
| `limit` | Optional. Page size, default `100`, min `1`, max `500`. |

**Which claims are included**

The endpoint lists claims that require fraud/SIU filing visibility:

- `status` is `fraud_suspected` or `fraud_confirmed`, **or**
- `status` is `under_investigation` **and** the claim has a fraud-specific signal: `claim_type = 'fraud'` **or** `siu_case_id` is set.

Claims in `under_investigation` for non-fraud work (for example coverage verification) are **not** returned, so they are not shown as out of compliance with fraud filing rules.

**Response shape**

JSON object:

- `claims`: array of claim summaries.
- `total`: number of claims in the response (same as `len(claims)` for this endpoint).

Each element of `claims` includes:

| Field | Description |
|-------|-------------|
| `claim_id` | Claim identifier |
| `status` | Current claim status |
| `claim_type` | Claim type string |
| `siu_case_id` | SIU case id if any |
| `loss_state` | Loss state |
| `state_report_filed` | Whether a `state_bureau` filing exists |
| `nicb_filed` | Whether an `nicb` filing exists |
| `niss_filed` | Whether a `niss` filing exists |
| `required_filing_types` | Mandatory filing types for this claim given status and fraud signal (e.g. `["state_bureau"]`, or `["state_bureau","nicb","niss"]` for `fraud_confirmed`) |
| `missing_required_filings` | Subset of `required_filing_types` with no matching row in `fraud_report_filings` |
| `compliant` | `true` if `missing_required_filings` is empty |
| `filings` | List of filing records (type, report id, state, filed time) |

**Rules for `required_filing_types`**

- `fraud_suspected`: `state_bureau`
- `under_investigation` with a fraud signal (`claim_type` fraud or `siu_case_id` present): `state_bureau`
- `fraud_confirmed`: `state_bureau`, `nicb`, and `niss`

Other statuses are not returned by this endpoint’s claim filter.

For OpenAPI details and interactive testing, run the API server and open `/api/openapi/docs` (see [Getting Started](getting-started.md)).
