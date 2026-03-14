"""Crews for claim workflows."""

from claim_agent.crews.bodily_injury_crew import create_bodily_injury_crew
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew
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
from claim_agent.crews.settlement_crew import create_settlement_crew
from claim_agent.crews.subrogation_crew import create_subrogation_crew
from claim_agent.crews.salvage_crew import create_salvage_crew
from claim_agent.crews.supplemental_crew import create_supplemental_crew
from claim_agent.crews.rental_crew import create_rental_crew
from claim_agent.crews.reopened_crew import create_reopened_crew
from claim_agent.crews.follow_up_crew import create_follow_up_crew
from claim_agent.crews.siu_crew import create_siu_crew

__all__ = [
    "create_bodily_injury_crew",
    "AgentConfig",
    "TaskConfig",
    "create_crew",
    "create_main_crew",
    "create_router_crew",
    "run_claim_workflow",
    "create_new_claim_crew",
    "create_duplicate_crew",
    "create_total_loss_crew",
    "create_fraud_detection_crew",
    "create_partial_loss_crew",
    "create_escalation_crew",
    "create_settlement_crew",
    "create_subrogation_crew",
    "create_salvage_crew",
    "create_supplemental_crew",
    "create_rental_crew",
    "create_reopened_crew",
    "create_follow_up_crew",
    "create_siu_crew",
]
