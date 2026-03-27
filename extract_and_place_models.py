#!/usr/bin/env python3
"""
Extract model classes from claims.py and place them in the appropriate route modules.
"""

import re
from pathlib import Path
from typing import Dict, List

# Map model classes to the modules that use them
MODEL_TO_MODULE = {
    "AssignBody": "claims_review",
    "RejectBody": "claims_review",
    "RequestInfoBody": "claims_review",
    "ReviewerDecisionBody": "claims_review",
    "ApproveBody": "claims_review",
    "FollowUpRunBody": "claims_specialized",
    "RecordFollowUpResponseBody": "claims_specialized",
    "DisputeBody": "claims_specialized",
    "DisputeResponse": "claims_specialized",
    "SupplementalBody": "claims_specialized",
    "SupplementalResponse": "claims_specialized",
    "DenialCoverageBody": "claims_specialized",
    "DenialCoverageResponse": "claims_specialized",
    "PartyConsentUpdate": "claims_parties",
    "CreatePartyRelationshipBody": "claims_parties",
    "CreatePortalTokenBody": "claims_parties",
    "CreateRepairShopPortalTokenBody": "claims_parties",
    "CreateThirdPartyPortalTokenBody": "claims_parties",
    "AssignRepairShopBody": "claims_parties",
    "DocumentUpdateBody": "claims_documents",
    "DocumentRequestCreateBody": "claims_documents",
    "DocumentRequestUpdateBody": "claims_documents",
    "ReserveBody": "claims_financial",
    "LitigationHoldBody": "claims_financial",
    "RepairStatusUpdateBody": "claims_financial",
    "AddNoteBody": "claims_audit",
}

def extract_class_code(lines: List[str], class_name: str) -> str | None:
    """Extract a class definition from the file."""
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(rf'^class {class_name}\(', line):
            # Found the class, now find its end
            class_indent = len(line) - len(line.lstrip())
            class_lines = [line]
            i += 1
            
            while i < len(lines):
                curr_line = lines[i]
                # Skip empty lines
                if not curr_line.strip():
                    class_lines.append(curr_line)
                    i += 1
                    continue
                
                curr_indent = len(curr_line) - len(curr_line.lstrip())
                # If we hit something at same or lower indent, class ended
                if curr_indent <= class_indent:
                    break
                
                class_lines.append(curr_line)
                i += 1
            
            return '\n'.join(class_lines)
        
        i += 1
    
    return None

def insert_models_into_module(module_path: Path, models: List[str], lines: List[str]):
    """Insert model classes into a module file after imports."""
    module_content = module_path.read_text()
    module_lines = module_content.split('\n')
    
    # Find where to insert (after RequireAdjuster/RequireSupervisor definitions)
    insert_idx = 0
    for i, line in enumerate(module_lines):
        if line.startswith('RequireSupervisor = '):
            insert_idx = i + 1
            break
        elif line.startswith('RequireAdjuster = '):
            insert_idx = i + 1
    
    # Extract model code
    model_codes = []
    for model_name in models:
        code = extract_class_code(lines, model_name)
        if code:
            model_codes.append(code)
        else:
            print(f"WARNING: Could not find {model_name}")
    
    if not model_codes:
        return
    
    # Insert models
    new_lines = (
        module_lines[:insert_idx] +
        ['', '# Request/Response Models', ''] +
        [code for codes in model_codes for code in (codes, '', '')]  +  
        module_lines[insert_idx:]
    )
    
    module_path.write_text('\n'.join(new_lines))
    print(f"Added {len(model_codes)} models to {module_path.name}")

def main():
    claims_file = Path("src/claim_agent/api/routes/claims.py")
    routes_dir = Path("src/claim_agent/api/routes")
    
    content = claims_file.read_text()
    lines = content.split('\n')
    
    # Group models by module
    module_models: Dict[str, List[str]] = {}
    for model_name, module_name in MODEL_TO_MODULE.items():
        if module_name not in module_models:
            module_models[module_name] = []
        module_models[module_name].append(model_name)
    
    # Insert models into each module
    for module_name, models in module_models.items():
        module_path = routes_dir / f"{module_name}.py"
        if module_path.exists():
            insert_models_into_module(module_path, models, lines)
        else:
            print(f"WARNING: Module {module_path} does not exist")
    
    print("\nDone!")

if __name__ == "__main__":
    main()
