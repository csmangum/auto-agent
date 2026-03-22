"""Pluggable adapters for external system integrations.

Use the ``get_*_adapter()`` functions to obtain the configured adapter
for each external system.  The backend is selected via environment
variables (default: ``mock``).
"""

from claim_agent.adapters.registry import (
    get_claim_search_adapter,
    get_gap_insurance_adapter,
    get_fraud_reporting_adapter,
    get_nmvtis_adapter,
    get_ocr_adapter,
    get_parts_adapter,
    get_policy_adapter,
    get_repair_shop_adapter,
    get_siu_adapter,
    get_valuation_adapter,
    reset_adapters,
)

__all__ = [
    "get_claim_search_adapter",
    "get_fraud_reporting_adapter",
    "get_gap_insurance_adapter",
    "get_nmvtis_adapter",
    "get_ocr_adapter",
    "get_parts_adapter",
    "get_policy_adapter",
    "get_repair_shop_adapter",
    "get_siu_adapter",
    "get_valuation_adapter",
    "reset_adapters",
]
