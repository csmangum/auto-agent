"""Tests for actuarial reserve reporting (aggregate, development export, adequacy summary)."""

from claim_agent.db.repository import ClaimRepository
from claim_agent.db.reserve_reporting import (
    aggregate_reserves_by_period,
    reserve_adequacy_summary,
    reserve_development_rows,
    reserve_development_triangle,
)
from claim_agent.models.claim import ClaimInput


def _sample_claim(policy_suffix: str = "RPT") -> ClaimInput:
    return ClaimInput(
        policy_number=f"POL-{policy_suffix}",
        vin="1HGBH41JXMN109300",
        vehicle_year=2020,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date="2024-06-15",
        incident_description="Rear-end",
        damage_description="Bumper",
        estimated_damage=4000.0,
    )


def test_aggregate_by_period_net_movement(temp_db):
    repo = ClaimRepository(db_path=temp_db)
    cid = repo.create_claim(_sample_claim())
    # FNOL inserts reserve_history from estimated_damage (4000) when configured
    repo.adjust_reserve(cid, 3000.0, reason="Down", actor_id="workflow")
    repo.adjust_reserve(cid, 4500.0, reason="Supplement", actor_id="workflow")

    out = aggregate_reserves_by_period(
        db_path=temp_db,
        date_from="2000-01-01",
        date_to="2099-01-01",
        granularity="month",
    )
    assert out["granularity"] == "month"
    assert len(out["periods"]) >= 1
    p0 = out["periods"][0]
    assert p0["change_count"] == 3
    # 4000 + (3000-4000) + (4500-3000) = 4500
    assert float(p0["net_movement"]) == 4500.0


def test_aggregate_filter_status(temp_db):
    repo = ClaimRepository(db_path=temp_db)
    c1 = repo.create_claim(_sample_claim("A"))
    c2 = repo.create_claim(_sample_claim("B"))
    repo.adjust_reserve(c1, 1000.0, actor_id="workflow")
    repo.adjust_reserve(c2, 2000.0, actor_id="workflow")
    out = aggregate_reserves_by_period(
        db_path=temp_db,
        date_from="2000-01-01",
        date_to="2099-01-01",
        status="pending",
    )
    total_changes = sum(int(p["change_count"]) for p in out["periods"])
    assert total_changes == 4  # FNOL reserve row per claim + one adjust each


def test_development_rows_pagination(temp_db):
    repo = ClaimRepository(db_path=temp_db)
    cid = repo.create_claim(_sample_claim())
    for i in range(3):
        repo.adjust_reserve(cid, 1000.0 * (i + 1), actor_id="workflow")

    page, total = reserve_development_rows(
        db_path=temp_db,
        date_from="2000-01-01",
        date_to="2099-01-01",
        limit=2,
        offset=0,
    )
    assert total == 4  # FNOL reserve row + 3 adjusts
    assert len(page) == 2
    page2, _ = reserve_development_rows(
        db_path=temp_db,
        date_from="2000-01-01",
        date_to="2099-01-01",
        limit=2,
        offset=2,
    )
    assert len(page2) == 2


def test_triangle_has_cells(temp_db):
    repo = ClaimRepository(db_path=temp_db)
    cid = repo.create_claim(_sample_claim())
    repo.adjust_reserve(cid, 2500.0, actor_id="workflow")
    tri = reserve_development_triangle(
        db_path=temp_db,
        date_from="2000-01-01",
        date_to="2099-01-01",
    )
    assert tri["cells"]
    assert 2024 in tri["accident_years"]


def test_adequacy_summary_counts(temp_db):
    repo = ClaimRepository(db_path=temp_db)
    repo.create_claim(_sample_claim("OK"))
    low = _sample_claim("LOW")
    low.estimated_damage = 5000.0
    cid_low = repo.create_claim(low)
    repo.adjust_reserve(cid_low, 1000.0, actor_id="workflow")

    s = reserve_adequacy_summary(db_path=temp_db)
    assert s["claim_count"] >= 2
    assert s["adequate_count"] + s["inadequate_count"] == s["claim_count"]
    assert s["inadequate_count"] >= 1


def test_adequacy_summary_with_filters(temp_db):
    """Regression test: ensure reserve_adequacy_summary works with claim_type/status filters."""
    from claim_agent.db.database import get_connection
    from sqlalchemy import text

    repo = ClaimRepository(db_path=temp_db)
    cid1 = repo.create_claim(_sample_claim("A"))
    cid2 = repo.create_claim(_sample_claim("B"))

    with get_connection(temp_db) as conn:
        conn.execute(
            text("UPDATE claims SET claim_type = :ct WHERE id = :cid"),
            {"ct": "partial_loss", "cid": cid1},
        )
        conn.execute(
            text("UPDATE claims SET claim_type = :ct WHERE id = :cid"),
            {"ct": "total_loss", "cid": cid2},
        )

    s_all = reserve_adequacy_summary(db_path=temp_db)
    assert s_all["claim_count"] >= 2

    s_partial = reserve_adequacy_summary(db_path=temp_db, claim_type="partial_loss")
    assert s_partial["claim_count"] >= 1
    assert s_partial["claim_count"] < s_all["claim_count"]

    s_pending = reserve_adequacy_summary(db_path=temp_db, status="pending")
    assert s_pending["claim_count"] >= 2
