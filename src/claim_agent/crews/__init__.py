"""Crews for claim workflows."""

from claim_agent.crews.main_crew import (
    create_main_crew,
    create_router_crew,
    run_claim_workflow,
)
from claim_agent.crews.new_claim_crew import create_new_claim_crew
from claim_agent.crews.duplicate_crew import create_duplicate_crew
from claim_agent.crews.total_loss_crew import create_total_loss_crew
from claim_agent.crews.fraud_detection_crew import create_fraud_detection_crew
from claim_agent.crews.partial_loss_crew import create_partial_loss_crew
from claim_agent.crews.escalation_crew import create_escalation_crew

__all__ = [
    "create_main_crew",
    "create_router_crew",
    "run_claim_workflow",
    "create_new_claim_crew",
    "create_duplicate_crew",
    "create_total_loss_crew",
    "create_fraud_detection_crew",
    "create_partial_loss_crew",
    "create_escalation_crew",
]
