#!/usr/bin/env python3
"""
Systematically split claims.py into focused route modules.

This script reads the claims.py file and extracts routes into separate module files
based on their functional domain.
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple

# Route module assignments
ROUTE_MODULES = {
    "claims_crud": [
        "get_claims_stats",
        "list_claims",
        "get_review_queue",
        "get_claim_status",
        "get_claim",
        "create_claim",
    ],
    "claims_review": [
        "assign_claim",
        "acknowledge_claim",
        "approve_review",
        "reject_review",
        "request_info_review",
        "escalate_to_siu",
        "run_claim_review",
    ],
    "claims_workflow": [
        "process_claim",
        "process_claim_async",
        "stream_claim_updates",
        "reprocess_claim",
    ],
    "claims_specialized": [
        "run_follow_up",
        "record_follow_up_response",
        "get_follow_up_messages",
        "run_siu_investigation",
        "file_dispute",
        "run_denial_coverage",
        "file_supplemental",
    ],
    "claims_documents": [
        "get_claim_attachment",
        "list_claim_documents",
        "upload_claim_document",
        "update_claim_document",
        "list_document_requests",
        "create_document_request",
        "update_document_request",
    ],
    "claims_parties": [
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
    "claims_incidents": [
        "create_incident",
        "get_incident",
        "create_claim_link",
        "get_related_claims",
        "allocate_bi",
    ],
    "claims_financial": [
        "patch_claim_litigation_hold",
        "patch_claim_reserve",
        "get_claim_reserve_history",
        "get_claim_reserve_adequacy",
        "get_claim_repair_status",
        "update_claim_repair_status",
    ],
    "claims_audit": [
        "get_claim_history",
        "get_claim_fraud_filings",
        "get_claim_notes",
        "add_claim_note",
        "get_claim_workflows",
    ],
    "claims_mock": [
        "generate_and_submit_claim",
        "generate_incident_details",
    ],
}

def find_function_extent(lines: List[str], start_idx: int) -> int:
    """Find the end line of a function starting at start_idx."""
    # Find the function definition line
    func_idx = start_idx
    while func_idx < len(lines) and not (lines[func_idx].strip().startswith('def ') or lines[func_idx].strip().startswith('async def ')):
        func_idx += 1
    
    if func_idx >= len(lines):
        return start_idx
    
    # Get the indentation of the function definition
    func_indent = len(lines[func_idx]) - len(lines[func_idx].lstrip())
    
    # Scan forward to find where the function ends
    i = func_idx + 1
    while i < len(lines):
        line = lines[i]
        # Skip empty lines and comments
        if not line.strip() or line.strip().startswith('#'):
            i += 1
            continue
        
        # Check indentation
        curr_indent = len(line) - len(line.lstrip())
        
        # If we hit something at the same or lower indentation level, function ended
        if curr_indent <= func_indent:
            return i - 1
        
        i += 1
    
    return len(lines) - 1

def extract_route_functions(content: str) -> Dict[str, Tuple[int, int]]:
    """Extract all route functions with their line ranges."""
    lines = content.split('\n')
    routes = {}
    
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith('@router.'):
            # Find the function name
            j = i
            while j < len(lines) and not (lines[j].strip().startswith('def ') or lines[j].strip().startswith('async def ')):
                j += 1
            
            if j < len(lines):
                func_match = re.search(r'(?:async\s+)?def\s+(\w+)', lines[j])
                if func_match:
                    func_name = func_match.group(1)
                    end_idx = find_function_extent(lines, i)
                    routes[func_name] = (i, end_idx)
                    i = end_idx + 1
                    continue
        
        i += 1
    
    return routes

def extract_helper_functions(content: str, end_of_imports: int) -> str:
    """Extract all helper functions and classes that routes depend on."""
    lines = content.split('\n')
    
    # Find helpers between imports and first route
    helpers = []
    i = end_of_imports
    
    while i < len(lines):
        line = lines[i]
        # Stop at first @router
        if line.strip().startswith('@router.'):
            break
        helpers.append(line)
        i += 1
    
    return '\n'.join(helpers)

def find_imports_end(lines: List[str]) -> int:
    """Find the last import line."""
    last_import = 0
    for i, line in enumerate(lines):
        if line.startswith('import ') or line.startswith('from '):
            last_import = i
    return last_import

def main():
    claims_file = Path("src/claim_agent/api/routes/claims.py")
    content = claims_file.read_text()
    lines = content.split('\n')
    
    # Find where imports end
    imports_end = find_imports_end(lines)
    print(f"Imports end at line {imports_end}")
    
    # Extract all route functions
    route_funcs = extract_route_functions(content)
    print(f"\nFound {len(route_funcs)} route functions")
    
    # Verify all assigned routes exist
    for module, funcs in ROUTE_MODULES.items():
        missing = [f for f in funcs if f not in route_funcs]
        if missing:
            print(f"WARNING: {module} has missing functions: {missing}")
    
    # Show line counts per module
    print("\nLines per module:")
    for module, funcs in ROUTE_MODULES.items():
        total_lines = sum(
            route_funcs[f][1] - route_funcs[f][0] + 1
            for f in funcs
            if f in route_funcs
        )
        print(f"  {module:25} {len(funcs):2} routes, ~{total_lines:4} lines")

if __name__ == "__main__":
    main()
