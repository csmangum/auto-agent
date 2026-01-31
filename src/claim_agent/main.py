"""CLI entry point for the claim agent."""

import json
import sys
from pathlib import Path

from pydantic import ValidationError

# Ensure src is on path when run as script
if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_CLAIM_DATA_KEYS = (
    "policy_number",
    "vin",
    "vehicle_year",
    "vehicle_make",
    "vehicle_model",
    "incident_date",
    "incident_description",
    "damage_description",
    "estimated_damage",
)

# Defaults for _claim_data_from_row when row has None (required for ClaimInput)
_CLAIM_DATA_DEFAULTS = {
    "policy_number": "",
    "vin": "",
    "vehicle_year": 0,
    "vehicle_make": "",
    "vehicle_model": "",
    "incident_date": "",
    "incident_description": "",
    "damage_description": "",
    "estimated_damage": None,
}


def _usage() -> str:
    return """Usage:
  claim-agent process <claim.json>   Process a new claim from JSON file
  claim-agent status <claim_id>     Get claim status
  claim-agent history <claim_id>     Get claim audit log
  claim-agent reprocess <claim_id>   Re-run workflow for an existing claim
  claim-agent <claim.json>           Same as process (legacy)
"""


def _claim_data_from_row(row: dict) -> dict:
    """Build full claim_data dict from a claim row for reprocess. Uses defaults for None."""
    return {
        k: row.get(k) if row.get(k) is not None else _CLAIM_DATA_DEFAULTS[k]
        for k in _CLAIM_DATA_KEYS
    }


def cmd_process(claim_path: Path) -> None:
    """Process a claim from a JSON file."""
    if not claim_path.exists():
        print(f"Error: File not found: {claim_path}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(claim_path, encoding="utf-8") as f:
            claim_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {claim_path}: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        from claim_agent.models.claim import ClaimInput
        ClaimInput.model_validate(claim_data)
    except ValidationError as e:
        print("Error: Invalid claim data:", file=sys.stderr)
        print(e.json() if hasattr(e, "json") else str(e), file=sys.stderr)
        sys.exit(1)
    from claim_agent.crews.main_crew import run_claim_workflow
    result = run_claim_workflow(claim_data)
    print(json.dumps(result, indent=2))


def cmd_status(claim_id: str) -> None:
    """Print claim status."""
    from claim_agent.db.repository import ClaimRepository
    repo = ClaimRepository()
    claim = repo.get_claim(claim_id)
    if claim is None:
        print(f"Error: Claim not found: {claim_id}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(claim, indent=2))


def cmd_history(claim_id: str) -> None:
    """Print claim audit log."""
    from claim_agent.db.repository import ClaimRepository
    repo = ClaimRepository()
    claim = repo.get_claim(claim_id)
    if claim is None:
        print(f"Error: Claim not found: {claim_id}", file=sys.stderr)
        sys.exit(1)
    history = repo.get_claim_history(claim_id)
    print(json.dumps(history, indent=2))


def cmd_reprocess(claim_id: str) -> None:
    """Re-run workflow for an existing claim."""
    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput
    repo = ClaimRepository()
    claim = repo.get_claim(claim_id)
    if claim is None:
        print(f"Error: Claim not found: {claim_id}", file=sys.stderr)
        sys.exit(1)
    claim_data = _claim_data_from_row(claim)
    try:
        ClaimInput.model_validate(claim_data)
    except ValidationError as e:
        print("Error: Invalid claim data for reprocess:", file=sys.stderr)
        print(e.json() if hasattr(e, "json") else str(e), file=sys.stderr)
        sys.exit(1)
    try:
        result = run_claim_workflow(claim_data, existing_claim_id=claim_id)
        print(json.dumps(result, indent=2))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Run the claim agent: process, status, history, or reprocess."""
    argv = sys.argv[1:]
    if not argv:
        print(_usage(), file=sys.stderr)
        sys.exit(1)

    first = argv[0].lower()
    if first in ("status", "history", "reprocess"):
        if len(argv) < 2:
            print(f"Error: {first} requires <claim_id>", file=sys.stderr)
            print(_usage(), file=sys.stderr)
            sys.exit(1)
        claim_id = argv[1]
        if first == "status":
            cmd_status(claim_id)
        elif first == "history":
            cmd_history(claim_id)
        else:
            cmd_reprocess(claim_id)
        return

    if first == "process":
        if len(argv) < 2:
            print("Error: process requires <claim.json>", file=sys.stderr)
            print(_usage(), file=sys.stderr)
            sys.exit(1)
        path = Path(argv[1])
        cmd_process(path)
        return

    # Legacy: single argument is a file path (process)
    path = Path(first)
    if path.suffix and path.exists():
        cmd_process(path)
        return
    print(f"Error: Unknown command or file not found: {first}", file=sys.stderr)
    print(_usage(), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
