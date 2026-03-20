"""Aggregate reserve / IBNR-oriented reporting over ``reserve_history`` and ``claims``.

SQLite and PostgreSQL compatible (date bucketing and functions differ by dialect).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import text

from claim_agent.db.database import _is_postgres, get_connection, row_to_dict

Granularity = Literal["month", "quarter"]


def _default_date_range() -> tuple[str, str]:
    """Last 12 months, end exclusive (``date_to`` is tomorrow UTC date)."""
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=366)
    return start.isoformat(), end.isoformat()


def _period_sql(granularity: Granularity) -> str:
    if _is_postgres():
        if granularity == "quarter":
            return (
                "TO_CHAR(h.created_at, 'YYYY') || '-Q' || "
                "EXTRACT(QUARTER FROM h.created_at)::INT::TEXT"
            )
        return "TO_CHAR(h.created_at, 'YYYY-MM')"
    if granularity == "quarter":
        return (
            "strftime('%Y', h.created_at) || '-Q' || "
            "CAST((CAST(strftime('%m', h.created_at) AS INTEGER) + 2) / 3 AS TEXT)"
        )
    return "strftime('%Y-%m', h.created_at)"


def _benchmark_sql(table_alias: str = "") -> str:
    """Expression for max(positive est, positive payout), else NULL (matches adequacy logic)."""
    p = f"{table_alias}." if table_alias else ""
    est = f"{p}estimated_damage"
    pay = f"{p}payout_amount"
    if _is_postgres():
        # GREATEST ignores NULL in some cases but returns NULL if any arg is NULL in PG;
        # mirror the SQLite branch logic for one-sided positives.
        return f"""
            CASE
                WHEN (COALESCE({est}, 0) <= 0 AND COALESCE({pay}, 0) <= 0) THEN NULL
                WHEN COALESCE({est}, 0) > 0 AND COALESCE({pay}, 0) > 0 THEN GREATEST({est}, {pay})
                WHEN COALESCE({est}, 0) > 0 THEN {est}
                ELSE {pay}
            END
        """
    # SQLite: two-arg MAX(x,y) returns NULL if either side is NULL; use explicit branches.
    return f"""
        CASE
            WHEN IFNULL({est}, 0) <= 0 AND IFNULL({pay}, 0) <= 0 THEN NULL
            WHEN IFNULL({est}, 0) > 0 AND IFNULL({pay}, 0) > 0 THEN MAX({est}, {pay})
            WHEN IFNULL({est}, 0) > 0 THEN {est}
            ELSE {pay}
        END
    """


def _development_sql() -> tuple[str, str]:
    """Returns (dev_lag_expr, accident_year_expr) for development triangle/rows.
    
    dev_lag_expr: months between incident_date and valuation_at
    accident_year_expr: year extracted from incident_date
    """
    if _is_postgres():
        dev_lag = (
            "(EXTRACT(YEAR FROM h.created_at::timestamp)::INT - "
            "EXTRACT(YEAR FROM c.incident_date::timestamp)::INT) * 12 + "
            "(EXTRACT(MONTH FROM h.created_at::timestamp)::INT - "
            "EXTRACT(MONTH FROM c.incident_date::timestamp)::INT)"
        )
        accident_y = "EXTRACT(YEAR FROM c.incident_date::timestamp)::INT"
    else:
        dev_lag = (
            "(CAST(strftime('%Y', h.created_at) AS INTEGER) - "
            "CAST(strftime('%Y', c.incident_date) AS INTEGER)) * 12 + "
            "(CAST(strftime('%m', h.created_at) AS INTEGER) - "
            "CAST(strftime('%m', c.incident_date) AS INTEGER))"
        )
        accident_y = "CAST(strftime('%Y', c.incident_date) AS INTEGER)"
    return dev_lag, accident_y


def _apply_claim_filters(
    filters: list[str],
    params: dict[str, Any],
    *,
    table_alias: str,
    claim_type: str | None,
    status: str | None,
) -> None:
    t = f"{table_alias}." if table_alias else ""
    if claim_type:
        filters.append(f"{t}claim_type = :claim_type")
        params["claim_type"] = claim_type.strip()
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            placeholders = ", ".join(f":st{i}" for i in range(len(statuses)))
            for i, s in enumerate(statuses):
                params[f"st{i}"] = s
            filters.append(f"{t}status IN ({placeholders})")


def aggregate_reserves_by_period(
    *,
    db_path: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    granularity: Granularity = "month",
    claim_type: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Sum net reserve movements and activity by calendar month or quarter.

    Net movement per row is ``new_amount - COALESCE(old_amount, 0)`` (initial set
    counts as full ``new_amount``). Filters apply to the joined claim row.
    """
    start, end = _default_date_range()
    d0 = date_from or start
    d1 = date_to or end
    period_expr = _period_sql(granularity)
    filters: list[str] = [
        "h.created_at >= :d0",
        "h.created_at < :d1",
    ]
    params: dict[str, Any] = {"d0": d0, "d1": d1}
    _apply_claim_filters(filters, params, table_alias="c", claim_type=claim_type, status=status)
    where_sql = " AND ".join(filters)

    q = f"""
        SELECT {period_expr} AS period,
               COUNT(*) AS change_count,
               COUNT(DISTINCT h.claim_id) AS distinct_claims,
               SUM(h.new_amount - COALESCE(h.old_amount, 0)) AS net_movement,
               SUM(h.new_amount) AS sum_new_amount
        FROM reserve_history h
        INNER JOIN claims c ON c.id = h.claim_id
        WHERE {where_sql}
        GROUP BY 1
        ORDER BY 1 ASC
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(text(q), params).fetchall()
    periods = [dict(row_to_dict(r)) for r in rows]
    return {
        "granularity": granularity,
        "date_from": d0,
        "date_to": d1,
        "claim_type_filter": claim_type,
        "status_filter": status,
        "periods": periods,
    }


def reserve_development_rows(
    *,
    db_path: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    claim_type: str | None = None,
    status: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Paginated reserve changes joined to claim attributes for IBNR / development work."""
    start, end = _default_date_range()
    d0 = date_from or start
    d1 = date_to or end
    filters: list[str] = [
        "h.created_at >= :d0",
        "h.created_at < :d1",
    ]
    params: dict[str, Any] = {"d0": d0, "d1": d1}
    _apply_claim_filters(filters, params, table_alias="c", claim_type=claim_type, status=status)
    where_sql = " AND ".join(filters)

    count_params = {k: v for k, v in params.items()}
    params["limit"] = limit
    params["offset"] = offset

    count_q = f"""
        SELECT COUNT(*) AS n
        FROM reserve_history h
        INNER JOIN claims c ON c.id = h.claim_id
        WHERE {where_sql}
    """
    dev_lag, accident_y = _development_sql()

    data_q = f"""
        SELECT
            h.id AS history_id,
            h.claim_id,
            h.old_amount,
            h.new_amount,
            (h.new_amount - COALESCE(h.old_amount, 0)) AS net_movement,
            h.reason,
            h.actor_id,
            h.created_at AS valuation_at,
            c.incident_date,
            c.claim_type,
            c.status,
            c.estimated_damage,
            c.payout_amount,
            c.reserve_amount AS current_reserve,
            CASE WHEN c.incident_date IS NULL OR c.incident_date = '' THEN NULL
                 ELSE {accident_y} END AS accident_year,
            CASE WHEN c.incident_date IS NULL OR c.incident_date = '' THEN NULL
                 ELSE {dev_lag} END AS development_month
        FROM reserve_history h
        INNER JOIN claims c ON c.id = h.claim_id
        WHERE {where_sql}
        ORDER BY h.id ASC
        LIMIT :limit OFFSET :offset
    """
    with get_connection(db_path) as conn:
        count_row = conn.execute(text(count_q), count_params).fetchone()
        total = int(count_row[0]) if count_row and count_row[0] is not None else 0
        rows = conn.execute(text(data_q), params).fetchall()
    return [row_to_dict(r) for r in rows], total


def reserve_development_triangle(
    *,
    db_path: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    claim_type: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Bucketed net reserve movements by accident year and development month (0-based)."""
    start, end = _default_date_range()
    d0 = date_from or start
    d1 = date_to or end
    filters: list[str] = [
        "h.created_at >= :d0",
        "h.created_at < :d1",
        "c.incident_date IS NOT NULL",
        "c.incident_date != ''",
    ]
    params: dict[str, Any] = {"d0": d0, "d1": d1}
    _apply_claim_filters(filters, params, table_alias="c", claim_type=claim_type, status=status)
    where_sql = " AND ".join(filters)

    dev_lag, accident_y = _development_sql()

    q = f"""
        SELECT
            {accident_y} AS accident_year,
            {dev_lag} AS development_month,
            COUNT(*) AS entry_count,
            SUM(h.new_amount - COALESCE(h.old_amount, 0)) AS sum_net_movement
        FROM reserve_history h
        INNER JOIN claims c ON c.id = h.claim_id
        WHERE {where_sql}
        GROUP BY 1, 2
        HAVING {accident_y} IS NOT NULL AND {dev_lag} IS NOT NULL
        ORDER BY 1 ASC, 2 ASC
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(text(q), params).fetchall()
    cells = [row_to_dict(r) for r in rows]
    accident_years = sorted(
        {int(c["accident_year"]) for c in cells if c.get("accident_year") is not None}
    )
    dev_months = sorted(
        {int(c["development_month"]) for c in cells if c.get("development_month") is not None}
    )
    return {
        "date_from": d0,
        "date_to": d1,
        "claim_type_filter": claim_type,
        "status_filter": status,
        "accident_years": accident_years,
        "development_months": dev_months,
        "cells": cells,
        "note": (
            "Each cell is the sum of net reserve movements (new_amount - old_amount) for "
            "history rows whose valuation month is development_month months after the "
            "incident month. This is a simplified development view; treaty and regulatory "
            "reporting may require additional fields."
        ),
    }


def reserve_adequacy_summary(
    *,
    db_path: str | None = None,
    claim_type: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Aggregate counts aligned with ``check_reserve_adequacy`` / ``_reserve_adequacy_details``."""
    filters: list[str] = ["1=1"]
    params: dict[str, Any] = {}
    _apply_claim_filters(filters, params, table_alias="", claim_type=claim_type, status=status)
    where_sql = " AND ".join(filters)
    bench = _benchmark_sql("")

    q = f"""
        SELECT
            COUNT(*) AS claim_count,
            SUM(CASE
                WHEN reserve_amount IS NULL THEN
                    CASE WHEN ({bench}) IS NULL OR ({bench}) <= 0 THEN 1 ELSE 0 END
                WHEN ({bench}) IS NULL OR reserve_amount >= ({bench}) THEN 1
                ELSE 0
            END) AS adequate_count,
            SUM(CASE WHEN reserve_amount IS NULL THEN 0 ELSE reserve_amount END)
                AS total_reserve_on_claims_with_reserve,
            SUM(COALESCE(estimated_damage, 0)) AS sum_estimated_damage,
            SUM(COALESCE(payout_amount, 0)) AS sum_payout_amount
        FROM claims
        WHERE {where_sql}
    """
    with get_connection(db_path) as conn:
        row = conn.execute(text(q), params).fetchone()
    d = row_to_dict(row)
    claim_count = int(d.get("claim_count") or 0)
    adequate = int(d.get("adequate_count") or 0)
    pct = (adequate / claim_count * 100.0) if claim_count else 0.0
    return {
        "claim_count": claim_count,
        "adequate_count": adequate,
        "inadequate_count": claim_count - adequate,
        "pct_adequate": round(pct, 2),
        "total_reserve_on_claims_with_reserve": float(d.get("total_reserve_on_claims_with_reserve") or 0),
        "sum_estimated_damage": float(d.get("sum_estimated_damage") or 0),
        "sum_payout_amount": float(d.get("sum_payout_amount") or 0),
        "claim_type_filter": claim_type,
        "status_filter": status,
        "note": (
            "Adequate matches per-claim logic: reserve >= max(positive estimated_damage, "
            "positive payout) when a positive benchmark exists; no reserve is adequate when "
            "no positive benchmark. See GET /api/claims/{claim_id}/reserve/adequacy."
        ),
    }

