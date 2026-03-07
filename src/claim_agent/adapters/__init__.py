"""Pluggable adapters for external system integrations.

Use the ``get_*_adapter()`` functions to obtain the configured adapter
for each external system.  The backend is selected via environment
variables (default: ``mock``).
"""

from claim_agent.adapters.registry import (
    get_parts_adapter,
    get_policy_adapter,
    get_repair_shop_adapter,
    get_siu_adapter,
    get_valuation_adapter,
    reset_adapters,
)

__all__ = [
    "get_parts_adapter",
    "get_policy_adapter",
    "get_repair_shop_adapter",
    "get_siu_adapter",
    "get_valuation_adapter",
    "reset_adapters",
]
