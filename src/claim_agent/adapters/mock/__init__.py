"""Mock adapter implementations backed by mock_db.json."""

from claim_agent.adapters.mock.nmvtis import MockNMVTISAdapter
from claim_agent.adapters.mock.claim_search import MockClaimSearchAdapter
from claim_agent.adapters.mock.parts import MockPartsAdapter
from claim_agent.adapters.mock.policy import MockPolicyAdapter
from claim_agent.adapters.mock.repair_shop import MockRepairShopAdapter
from claim_agent.adapters.mock.siu import MockSIUAdapter
from claim_agent.adapters.mock.valuation import MockValuationAdapter

__all__ = [
    "MockNMVTISAdapter",
    "MockClaimSearchAdapter",
    "MockPartsAdapter",
    "MockPolicyAdapter",
    "MockRepairShopAdapter",
    "MockSIUAdapter",
    "MockValuationAdapter",
]
