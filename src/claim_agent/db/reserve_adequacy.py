"""Shared reserve adequacy evaluation (used by repository API and state machine gates)."""

from __future__ import annotations

from claim_agent.db.constants import (
    RESERVE_ADEQUACY_CODE_BELOW_BENCHMARK,
    RESERVE_ADEQUACY_CODE_BELOW_ESTIMATE,
    RESERVE_ADEQUACY_CODE_BELOW_PAYOUT,
    RESERVE_ADEQUACY_CODE_NOT_SET,
)


def compute_reserve_adequacy_details(
    reserve_val: float | None,
    est_val: float | None,
    payout_val: float | None,
) -> tuple[bool, list[str], list[str]]:
    """Compute adequacy, human warnings, and stable warning_codes.

    Matches ``check_reserve_adequacy`` / historical ``_reserve_adequacy_details`` logic.
    """
    warnings: list[str] = []
    codes: list[str] = []

    benchmark: float | None = None
    if payout_val is not None and payout_val > 0:
        benchmark = payout_val
    if est_val is not None and est_val > 0:
        benchmark = max(benchmark or 0, est_val)

    if reserve_val is None:
        if benchmark is not None and benchmark > 0:
            warnings.append(
                "No reserve set; reserve should be set for actuarial tracking",
            )
            codes.append(RESERVE_ADEQUACY_CODE_NOT_SET)
        adequate = benchmark is None or benchmark <= 0
        return adequate, warnings, codes

    if benchmark is None or reserve_val >= benchmark:
        return True, warnings, codes

    below_estimate = (
        est_val is not None
        and est_val == benchmark
        and (payout_val is None or payout_val <= 0 or payout_val < benchmark)
    )
    below_payout_only = (
        payout_val is not None
        and payout_val == benchmark
        and (est_val is None or est_val <= 0 or est_val < benchmark)
    )
    if below_estimate:
        warnings.append(
            f"Reserve ${reserve_val:,.2f} is below estimated damage ${benchmark:,.2f}",
        )
        codes.append(RESERVE_ADEQUACY_CODE_BELOW_ESTIMATE)
    elif below_payout_only:
        warnings.append(
            f"Reserve ${reserve_val:,.2f} is below payout ${benchmark:,.2f}",
        )
        codes.append(RESERVE_ADEQUACY_CODE_BELOW_PAYOUT)
    else:
        parts = []
        if est_val is not None:
            parts.append(f"estimated damage ${est_val:,.2f}")
        if payout_val is not None:
            parts.append(f"payout ${payout_val:,.2f}")
        suffix = f" ({', '.join(parts)})" if parts else ""
        warnings.append(
            f"Reserve ${reserve_val:,.2f} is below benchmark ${benchmark:,.2f}{suffix}",
        )
        codes.append(RESERVE_ADEQUACY_CODE_BELOW_BENCHMARK)
    return False, warnings, codes
