#!/usr/bin/env python3
"""Analyze claims.py routes for splitting into modules."""

import re
from pathlib import Path

claims_file = Path("src/claim_agent/api/routes/claims.py")
content = claims_file.read_text()

# Find all route definitions
route_pattern = r'@router\.(get|post|put|patch|delete)\("([^"]+)"[^\)]*\)\s*(?:async\s+)?def\s+(\w+)'
routes = re.findall(route_pattern, content)

# Group routes by category based on path
categories = {
    "stats_listing": [],
    "review_workflow": [],
    "workflow_processing": [],
    "documents": [],
    "parties_portals": [],
    "incidents": [],
    "specialized_workflows": [],
    "financial": [],
    "audit_history": [],
    "repair": [],
    "mock_generation": [],
}

for method, path, func_name in routes:
    route_info = f"{method.upper():6} {path:50} -> {func_name}"
    
    if path in ["/claims/stats", "/claims", "/claims/review-queue", "/claims/{claim_id}/status", "/claims/{claim_id}"]:
        categories["stats_listing"].append(route_info)
    elif any(x in path for x in ["/assign", "/acknowledge", "/review/approve", "/review/reject", "/review/request-info", "/review/escalate", "/review"]):
        categories["review_workflow"].append(route_info)
    elif any(x in path for x in ["/process", "/reprocess", "/stream"]):
        categories["workflow_processing"].append(route_info)
    elif any(x in path for x in ["/documents", "/document-requests", "/attachments"]):
        categories["documents"].append(route_info)
    elif any(x in path for x in ["/parties", "/portal-token", "/repair-shop-portal", "/third-party-portal", "/repair-shop-assignments"]):
        categories["parties_portals"].append(route_info)
    elif any(x in path for x in ["/incidents", "/claim-links", "/related", "/bi-allocation"]):
        categories["incidents"].append(route_info)
    elif any(x in path for x in ["/follow-up", "/siu", "/dispute", "/denial-coverage", "/supplemental"]):
        categories["specialized_workflows"].append(route_info)
    elif any(x in path for x in ["/reserve", "/litigation-hold"]):
        categories["financial"].append(route_info)
    elif any(x in path for x in ["/history", "/notes", "/fraud-filings", "/workflows"]):
        categories["audit_history"].append(route_info)
    elif "repair-status" in path:
        categories["repair"].append(route_info)
    elif "generate" in path:
        categories["mock_generation"].append(route_info)

print("=" * 80)
print("CLAIMS.PY ROUTE ANALYSIS")
print("=" * 80)
for category, routes_list in categories.items():
    if routes_list:
        print(f"\n{category.upper().replace('_', ' ')} ({len(routes_list)} routes):")
        print("-" * 80)
        for route in routes_list:
            print(f"  {route}")

print(f"\n\nTOTAL ROUTES: {sum(len(r) for r in categories.values())}")
