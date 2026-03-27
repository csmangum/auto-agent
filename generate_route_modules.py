#!/usr/bin/env python3
"""
Generate the split route module files from claims.py.
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple

# Route module assignments (same as before)
ROUTE_MODULES = {
    "claims_crud": {
        "routes": [
            "get_claims_stats",
            "list_claims",
            "get_review_queue",
            "get_claim_status",
            "get_claim",
            "create_claim",
        ],
        "description": "Core CRUD operations for claims: stats, listing, detail, creation.",
    },
    "claims_review": {
        "routes": [
            "assign_claim",
            "acknowledge_claim",
            "approve_review",
            "reject_review",
            "request_info_review",
            "escalate_to_siu",
            "run_claim_review",
        ],
        "description": "Review workflow operations: assignment, approval, rejection.",
    },
    "claims_workflow": {
        "routes": [
            "process_claim",
            "process_claim_async",
            "stream_claim_updates",
            "reprocess_claim",
        ],
        "description": "Workflow processing operations: process, reprocess, streaming.",
    },
    "claims_specialized": {
        "routes": [
            "run_follow_up",
            "record_follow_up_response",
            "get_follow_up_messages",
            "run_siu_investigation",
            "file_dispute",
            "run_denial_coverage",
            "file_supplemental",
        ],
        "description": "Specialized workflow operations: follow-up, SIU, disputes, denials, supplemental.",
    },
    "claims_documents": {
        "routes": [
            "get_claim_attachment",
            "list_claim_documents",
            "upload_claim_document",
            "update_claim_document",
            "list_document_requests",
            "create_document_request",
            "update_document_request",
        ],
        "description": "Document and attachment management.",
    },
    "claims_parties": {
        "routes": [
            "update_party_consent",
            "create_party_relationship",
            "delete_party_relationship",
            "create_portal_token",
            "create_repair_shop_portal_token",
            "assign_repair_shop_to_claim",
            "list_repair_shop_assignments",
            "remove_repair_shop_assignment",
            "create_third_party_portal_token",
        ],
        "description": "Party management and portal token generation.",
    },
    "claims_incidents": {
        "routes": [
            "create_incident",
            "get_incident",
            "create_claim_link",
            "get_related_claims",
            "allocate_bi",
        ],
        "description": "Incident management and BI allocation.",
    },
    "claims_financial": {
        "routes": [
            "patch_claim_litigation_hold",
            "patch_claim_reserve",
            "get_claim_reserve_history",
            "get_claim_reserve_adequacy",
            "get_claim_repair_status",
            "update_claim_repair_status",
        ],
        "description": "Financial operations: reserves, litigation hold, repair status.",
    },
    "claims_audit": {
        "routes": [
            "get_claim_history",
            "get_claim_fraud_filings",
            "get_claim_notes",
            "add_claim_note",
            "get_claim_workflows",
        ],
        "description": "Audit and history operations: notes, fraud filings, workflow history.",
    },
    "claims_mock": {
        "routes": [
            "generate_and_submit_claim",
            "generate_incident_details",
        ],
        "description": "Mock claim generation for testing (requires MOCK_CREW_ENABLED=true).",
    },
}

def find_function_extent(lines: List[str], start_idx: int) -> int:
    """Find the end line of a function starting at start_idx."""
    func_idx = start_idx
    while func_idx < len(lines) and not (lines[func_idx].strip().startswith('def ') or lines[func_idx].strip().startswith('async def ')):
        func_idx += 1
    
    if func_idx >= len(lines):
        return start_idx
    
    func_indent = len(lines[func_idx]) - len(lines[func_idx].lstrip())
    
    i = func_idx + 1
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith('#'):
            i += 1
            continue
        
        curr_indent = len(line) - len(line.lstrip())
        if curr_indent <= func_indent:
            return i - 1
        i += 1
    
    return len(lines) - 1

def extract_route_code(lines: List[str], start: int, end: int) -> str:
    """Extract route code including decorator."""
    # Back up to include all decorators
    decorator_start = start
    while decorator_start > 0 and (lines[decorator_start - 1].strip().startswith('@') or not lines[decorator_start - 1].strip()):
        if lines[decorator_start - 1].strip().startswith('@'):
            decorator_start -= 1
        else:
            break
    
    return '\n'.join(lines[decorator_start:end + 1])

def extract_route_functions(content: str) -> Dict[str, Tuple[int, int, str]]:
    """Extract all route functions with their line ranges and code."""
    lines = content.split('\n')
    routes = {}
    
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith('@router.'):
            j = i
            while j < len(lines) and not (lines[j].strip().startswith('def ') or lines[j].strip().startswith('async def ')):
                j += 1
            
            if j < len(lines):
                func_match = re.search(r'(?:async\s+)?def\s+(\w+)', lines[j])
                if func_match:
                    func_name = func_match.group(1)
                    end_idx = find_function_extent(lines, i)
                    code = extract_route_code(lines, i, end_idx)
                    routes[func_name] = (i, end_idx, code)
                    i = end_idx + 1
                    continue
        i += 1
    
    return routes

def generate_module_file(module_name: str, info: dict, route_funcs: dict, output_dir: Path):
    """Generate a route module file."""
    imports = '''"""''' + info["description"] + '''"""

import asyncio
import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import text

from claim_agent.api.auth import AuthContext
from claim_agent.api.claim_access import (
    adjuster_identity_scopes_assignee,
    ensure_claim_access_for_adjuster,
    filter_related_claim_ids_for_adjuster,
)
from claim_agent.api.idempotency import (
    get_idempotency_key_and_cached,
    release_idempotency_on_error,
    store_response_if_idempotent,
)
from claim_agent.api.deps import require_role
from claim_agent.api.routes._claims_helpers import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    PRIORITY_VALUES,
    STREAM_MAX_DURATION,
    STREAM_POLL_INTERVAL,
    VALID_DOCUMENT_TYPES,
    GenerateClaimRequest,
    GenerateIncidentDetailsRequest,
    adjuster_scope_params,
    apply_adjuster_claim_filter,
    background_tasks,
    background_tasks_lock,
    get_approve_lock,
    get_claim_context,
    http_already_processing,
    max_upload_file_size_bytes,
    resolve_attachment_urls,
    run_workflow_background,
    task_claim_ids,
    try_run_workflow_background,
    upload_file_size_exceeded_detail,
)
from claim_agent.config import get_settings
from claim_agent.context import ClaimContext
from claim_agent.crews.main_crew import run_claim_workflow
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.db.constants import *
from claim_agent.db.database import get_connection, get_db_path, row_to_dict
from claim_agent.db.incident_repository import IncidentRepository
from claim_agent.db.repository import ClaimRepository
from claim_agent.db.repair_status_repository import RepairStatusRepository
from claim_agent.db.document_repository import DocumentRepository, build_document_version_groups
from claim_agent.exceptions import *
from claim_agent.models.claim import Attachment, ClaimInput, ClaimRecord
from claim_agent.models.party import PartyRelationshipType
from claim_agent.models.incident import *
from claim_agent.models.document import DocumentRequestStatus, DocumentType, ReviewStatus
from claim_agent.models.dispute import DisputeType
from claim_agent.services.bi_allocation import allocate_bi_limits
from claim_agent.services.portal_verification import create_claim_access_token
from claim_agent.services.repair_shop_portal_tokens import create_repair_shop_access_token
from claim_agent.services.third_party_portal_tokens import create_third_party_access_token
from claim_agent.services.supplemental_request import execute_supplemental_request
from claim_agent.storage import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter
from claim_agent.storage.s3 import S3StorageAdapter
from claim_agent.tools.partial_loss_logic import _parse_partial_loss_workflow_output
from claim_agent.utils import attachment_type_to_document_type, infer_attachment_type
from claim_agent.utils.sanitization import *
from claim_agent.workflow.denial_coverage_orchestrator import run_denial_coverage_workflow
from claim_agent.workflow.dispute_orchestrator import run_dispute_workflow
from claim_agent.workflow.follow_up_orchestrator import run_follow_up_workflow
from claim_agent.workflow.handback_orchestrator import run_handback_workflow
from claim_agent.workflow.helpers import WORKFLOW_STAGES
from claim_agent.workflow.siu_orchestrator import run_siu_investigation as run_siu_investigation_workflow
from claim_agent.mock_crew.claim_generator import (
    generate_claim_from_prompt,
    generate_incident_damage_from_vehicle,
)
from claim_agent.db.repair_shop_user_repository import RepairShopUserRepository
from claim_agent.rag.constants import normalize_state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["claims"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")
RequireSupervisor = require_role("supervisor", "admin", "executive")

'''
    
    # Collect route functions
    routes_code = []
    for func_name in info["routes"]:
        if func_name in route_funcs:
            _, _, code = route_funcs[func_name]
            routes_code.append(code)
        else:
            print(f"WARNING: Function {func_name} not found in source")
    
    full_code = imports + "\n\n" + "\n\n\n".join(routes_code) + "\n"
    
    # Write to file
    output_file = output_dir / f"{module_name}.py"
    output_file.write_text(full_code)
    print(f"Generated {output_file} ({len(routes_code)} routes)")

def main():
    claims_file = Path("src/claim_agent/api/routes/claims.py")
    output_dir = Path("src/claim_agent/api/routes")
    
    content = claims_file.read_text()
    route_funcs = extract_route_functions(content)
    
    print(f"Extracting {len(route_funcs)} route functions into {len(ROUTE_MODULES)} modules...\n")
    
    for module_name, info in ROUTE_MODULES.items():
        generate_module_file(module_name, info, route_funcs, output_dir)
    
    print(f"\nDone! Created {len(ROUTE_MODULES)} new route modules.")

if __name__ == "__main__":
    main()
