"""BI coverage limit allocation when multiple claimants exceed per-accident limits.

When total BI demands exceed the policy's per_accident limit, allocate
proportionally (or by severity/equal) across claimants.
"""

from claim_agent.models.incident import BIAllocationInput, BIAllocationResult


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
        per_claimant = limit / len(demands)
        allocations = []
        for i, d in enumerate(demands):
            demanded = float(d.get("demanded_amount", 0) or 0)
            allocated = min(demanded, per_claimant)
            allocations.append({
                "claimant_id": d.get("claimant_id") or d.get("party_id", f"claimant_{i}"),
                "demanded": demanded,
                "allocated": allocated,
                "shortfall": demanded - allocated,
            })
    elif method == "severity_weighted":
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
        total_weight = sum(weights)
        allocations = []
        for i, d in enumerate(demands):
            demanded = float(d.get("demanded_amount", 0) or 0)
            share = limit * (weights[i] / total_weight)
            allocated = min(demanded, share)
            allocations.append({
                "claimant_id": d.get("claimant_id") or d.get("party_id", f"claimant_{i}"),
                "demanded": demanded,
                "allocated": allocated,
                "shortfall": demanded - allocated,
            })
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
