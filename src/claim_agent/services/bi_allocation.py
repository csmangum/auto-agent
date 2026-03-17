"""BI coverage limit allocation when multiple claimants exceed per-accident limits.

When total BI demands exceed the policy's per_accident limit, allocate
proportionally (or by severity/equal) across claimants.
"""

from claim_agent.models.incident import BIAllocationInput, BIAllocationResult


def _allocate_equal_with_redistribution(demands: list[dict], limit: float) -> list[dict]:
    """Allocate limit equally with iterative redistribution of excess capacity.

    When a claimant's demand is less than their equal share, redistribute
    the excess to remaining claimants with unmet demand.
    """
    n = len(demands)
    allocated = [0.0] * n
    demanded = [float(d.get("demanded_amount", 0) or 0) for d in demands]
    remaining_limit = limit
    active = [True] * n

    while remaining_limit > 0 and any(active):
        active_count = sum(active)
        if active_count == 0:
            break

        per_claimant = remaining_limit / active_count
        any_satisfied = False

        for i in range(n):
            if not active[i]:
                continue

            unmet = demanded[i] - allocated[i]
            if unmet <= per_claimant:
                allocated[i] += unmet
                remaining_limit -= unmet
                active[i] = False
                any_satisfied = True
            else:
                allocated[i] += per_claimant
                remaining_limit -= per_claimant

        if not any_satisfied:
            break

    allocations = []
    for i, d in enumerate(demands):
        allocations.append({
            "claimant_id": d.get("claimant_id") or d.get("party_id", f"claimant_{i}"),
            "demanded": demanded[i],
            "allocated": allocated[i],
            "shortfall": demanded[i] - allocated[i],
        })

    return allocations


def _allocate_severity_weighted_with_redistribution(
    demands: list[dict], limit: float
) -> list[dict]:
    """Allocate limit by severity weights with iterative redistribution.

    When a claimant's demand is less than their weighted share, redistribute
    the excess to remaining claimants with unmet demand, preserving relative weights.
    """
    weights = []
    for d in demands:
        sev = d.get("injury_severity")
        if sev is not None:
            try:
                w = float(sev)
            except (TypeError, ValueError):
                w = 1.0
        else:
            w = 1.0
        weights.append(max(0.1, min(10.0, w)))

    n = len(demands)
    allocated = [0.0] * n
    demanded = [float(d.get("demanded_amount", 0) or 0) for d in demands]
    remaining_limit = limit
    active = [True] * n

    while remaining_limit > 0 and any(active):
        total_weight = sum(weights[i] for i in range(n) if active[i])
        if total_weight == 0:
            break

        shares = [
            remaining_limit * (weights[i] / total_weight) if active[i] else 0.0
            for i in range(n)
        ]
        any_satisfied = False

        for i in range(n):
            if not active[i]:
                continue

            share = shares[i]
            unmet = demanded[i] - allocated[i]
            if unmet <= share:
                allocated[i] += unmet
                remaining_limit -= unmet
                active[i] = False
                any_satisfied = True
            else:
                allocated[i] += share
                remaining_limit -= share

        if not any_satisfied:
            break

    allocations = []
    for i, d in enumerate(demands):
        allocations.append({
            "claimant_id": d.get("claimant_id") or d.get("party_id", f"claimant_{i}"),
            "demanded": demanded[i],
            "allocated": allocated[i],
            "shortfall": demanded[i] - allocated[i],
        })

    return allocations


def allocate_bi_limits(input_data: BIAllocationInput) -> BIAllocationResult:
    """Allocate BI per-accident limit across multiple claimants.

    When total demands exceed the limit, applies the chosen allocation method:
    - proportional: each claimant gets (demand / total_demands) * limit
    - severity_weighted: weights by injury_severity (1-10), then proportional
    - equal: split limit equally among claimants
    """
    demands = input_data.claimant_demands
    limit = input_data.bi_per_accident_limit
    method = input_data.allocation_method

    if not demands:
        return BIAllocationResult(
            claim_id=input_data.claim_id,
            total_demanded=0,
            limit=limit,
            allocations=[],
            total_allocated=0,
            limit_exceeded=False,
        )

    total_demanded = sum(float(d.get("demanded_amount", 0) or 0) for d in demands)
    limit_exceeded = total_demanded > limit

    if not limit_exceeded:
        # No allocation needed; each gets full demand
        allocations = [
            {
                "claimant_id": d.get("claimant_id") or d.get("party_id", f"claimant_{i}"),
                "demanded": float(d.get("demanded_amount", 0) or 0),
                "allocated": float(d.get("demanded_amount", 0) or 0),
                "shortfall": 0,
            }
            for i, d in enumerate(demands)
        ]
        return BIAllocationResult(
            claim_id=input_data.claim_id,
            total_demanded=total_demanded,
            limit=limit,
            allocations=allocations,
            total_allocated=total_demanded,
            limit_exceeded=False,
        )

    # Allocation needed
    if method == "equal":
        allocations = _allocate_equal_with_redistribution(demands, limit)
    elif method == "severity_weighted":
        allocations = _allocate_severity_weighted_with_redistribution(demands, limit)
    else:
        # proportional (default)
        allocations = []
        for i, d in enumerate(demands):
            demanded = float(d.get("demanded_amount", 0) or 0)
            share = (demanded / total_demanded) * limit if total_demanded > 0 else 0
            allocated = min(demanded, share)
            allocations.append({
                "claimant_id": d.get("claimant_id") or d.get("party_id", f"claimant_{i}"),
                "demanded": demanded,
                "allocated": allocated,
                "shortfall": demanded - allocated,
            })

    total_allocated = sum(a["allocated"] for a in allocations)
    return BIAllocationResult(
        claim_id=input_data.claim_id,
        total_demanded=total_demanded,
        limit=limit,
        allocations=allocations,
        total_allocated=total_allocated,
        limit_exceeded=True,
    )
