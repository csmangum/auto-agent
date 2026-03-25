"""Mock adapter implementations, mostly backed by mock_db.json; MockGapInsuranceAdapter is in-memory only."""

from claim_agent.adapters.mock.claim_search import MockClaimSearchAdapter
from claim_agent.adapters.mock.fraud_reporting import MockFraudReportingAdapter
from claim_agent.adapters.mock.gap_insurance import MockGapInsuranceAdapter
from claim_agent.adapters.mock.medical_records import MockMedicalRecordsAdapter
from claim_agent.adapters.mock.nmvtis import MockNMVTISAdapter
from claim_agent.adapters.mock.parts import MockPartsAdapter
from claim_agent.adapters.mock.policy import MockPolicyAdapter
from claim_agent.adapters.mock.repair_shop import MockRepairShopAdapter
from claim_agent.adapters.mock.siu import MockSIUAdapter
from claim_agent.adapters.mock.state_bureau import MockStateBureauAdapter
from claim_agent.adapters.mock.valuation import MockValuationAdapter

__all__ = [
    "MockClaimSearchAdapter",
    "MockFraudReportingAdapter",
    "MockGapInsuranceAdapter",
    "MockMedicalRecordsAdapter",
    "MockNMVTISAdapter",
    "MockPartsAdapter",
    "MockPolicyAdapter",
    "MockRepairShopAdapter",
    "MockSIUAdapter",
    "MockStateBureauAdapter",
    "MockValuationAdapter",
]
