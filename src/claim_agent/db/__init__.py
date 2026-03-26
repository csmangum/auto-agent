"""SQLite database module for claim persistence and audit logging."""

from claim_agent.db.audit_events import (
    ACTOR_SYSTEM,
    ACTOR_WORKFLOW,
    AUDIT_EVENT_TYPES,
)
from claim_agent.db.database import (
    get_connection,
    get_connection_async,
    get_db_path,
    init_db,
    row_to_dict,
)
from claim_agent.db.repository import ClaimRepository
from claim_agent.db.note_repository import NoteRepository
from claim_agent.db.follow_up_repository import FollowUpRepository
from claim_agent.db.task_repository import TaskRepository
from claim_agent.db.subrogation_repository import SubrogationRepository
from claim_agent.db.workflow_repository import WorkflowRepository
from claim_agent.db.claim_party_repository import ClaimPartyRepository
from claim_agent.db.claim_search_repository import ClaimSearchRepository
from claim_agent.db.claim_retention_repository import ClaimRetentionRepository

__all__ = [
    "ACTOR_SYSTEM",
    "ACTOR_WORKFLOW",
    "AUDIT_EVENT_TYPES",
    "ClaimPartyRepository",
    "ClaimRepository",
    "ClaimRetentionRepository",
    "ClaimSearchRepository",
    "FollowUpRepository",
    "NoteRepository",
    "SubrogationRepository",
    "TaskRepository",
    "WorkflowRepository",
    "get_connection",
    "get_connection_async",
    "get_db_path",
    "init_db",
    "row_to_dict",
]
