# Actuarial reserve reporting (IBNR-oriented)

Supervisor, admin, and executive API roles can call aggregate endpoints over `reserve_history` and `claims` for regulatory, reinsurance, and internal loss-reserve analysis.

**Authentication:** same as other `/api/*` routes (`X-API-Key` or `Authorization: Bearer`). See [Configuration](configuration.md#authentication-and-rbac).

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/reports/reserves/by-period` | Net reserve **movements** by calendar month or quarter (`reserve_history.created_at`), optional `claim_type` and comma-separated `status`. |
| GET | `/api/reports/reserves/development` | **Paginated** join of each history row to claim dimensions, including `accident_year`, `development_month` (months after incident month), and `net_movement`. |
| GET | `/api/reports/reserves/triangle` | **Aggregated** `accident_year` × `development_month` cells (`sum_net_movement`, `entry_count`). |
| GET | `/api/reports/reserves/adequacy-summary` | Portfolio **adequate vs inadequate** counts using the same benchmark as `GET /api/claims/{claim_id}/reserve/adequacy` (max of positive `estimated_damage` and positive `payout_amount`). |

### Query parameters (common)

- `date_from`, `date_to` — optional ISO date/datetime; default window is roughly the last 12 months, with `date_to` **exclusive** (half-open interval).
- `claim_type` — optional exact match on `claims.claim_type`.
- `status` — optional comma-separated list (e.g. `open,pending`).

### Pagination (`/development`)

- `limit` — default `500`, maximum `5000`.
- `offset` — default `0`.
- Response includes `total`, `has_more`.

## Semantics

- **By-period “net movement”** is `SUM(new_amount - COALESCE(old_amount, 0))` per bucket. Initial reserve rows (no prior amount) contribute their full `new_amount`. This measures recorded strengthening/weakening in the period, not a full accounting triangle without additional data.
- **Development month** is `(valuation year − incident year) × 12 + (valuation month − incident month)` using `reserve_history.created_at` and `claims.incident_date`. Rows with missing `incident_date` are excluded from the triangle aggregation.
- **Adequacy summary** is an approximation suitable for dashboards; edge cases should be validated against per-claim `reserve/adequacy` if disputes arise.

## Performance

- SQLite and PostgreSQL are supported; date bucketing differs by dialect.
- Index `idx_reserve_history_created_at` on `reserve_history(created_at)` speeds time-range scans (migration `035` / fresh SQLite schema).

## Related

- [Database: `reserve_history`](database.md#reserve_history)
- [Configuration: reserve management](configuration.md#reserve-management)
