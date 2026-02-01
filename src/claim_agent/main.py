"""CLI entry point for the claim agent.

This module provides the command-line interface with full observability:
- Structured logging with claim context
- Optional metrics reporting
- LangSmith tracing integration
"""

import json
import logging
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


def _setup_logging() -> None:
    """Configure logging for CLI usage."""
    from claim_agent.observability import get_logger

    # Initialize root logger with observability configuration
    get_logger("claim_agent")
    # Also configure the root to capture all claim_agent.* logs
    logging.getLogger("claim_agent").setLevel(
        logging.DEBUG if "--debug" in sys.argv else logging.INFO
    )


def _usage() -> str:
    return """Usage:
  claim-agent process <claim.json>   Process a new claim from JSON file
  claim-agent status <claim_id>      Get claim status
  claim-agent history <claim_id>     Get claim audit log
  claim-agent reprocess <claim_id>   Re-run workflow for an existing claim
  claim-agent metrics [claim_id]     Show metrics (optionally for specific claim)
  claim-agent <claim.json>           Same as process (legacy)

Options:
  --debug                            Enable debug logging
  --json                             Use JSON log format
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
    try:
        result = run_claim_workflow(claim_data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: Claim processing failed: {e}", file=sys.stderr)
        sys.exit(1)


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


def cmd_metrics(claim_id: str | None = None) -> None:
    """Display metrics for claims.

    Args:
        claim_id: Optional claim ID. If provided, shows metrics for that claim.
                 Otherwise, shows global metrics summary.
    """
    from claim_agent.observability import get_metrics

    metrics = get_metrics()

    if claim_id:
        summary = metrics.get_claim_summary(claim_id)
        if summary is None:
            print(f"No metrics found for claim: {claim_id}", file=sys.stderr)
            print("Note: Metrics are only available for claims processed in the current session.")
            sys.exit(1)
        print(json.dumps(summary.to_dict(), indent=2, default=str))
    else:
        global_stats = metrics.get_global_stats()
        if global_stats["total_claims"] == 0:
            print("No claims have been processed in the current session.")
            print("Process some claims first to see metrics.")
            return
        print("Global Metrics Summary:")
        print(json.dumps(global_stats, indent=2, default=str))
        print("\nPer-Claim Summaries:")
        for summary in metrics.get_all_summaries():
            print(f"\n  {summary.claim_id}:")
            print(f"    LLM Calls: {summary.total_llm_calls}")
            print(f"    Tokens: {summary.total_tokens}")
            print(f"    Cost: ${summary.total_cost_usd:.4f}")
            print(f"    Latency: {summary.total_latency_ms:.0f}ms (avg: {summary.avg_latency_ms:.0f}ms)")
            print(f"    Status: {summary.status}")


def main() -> None:
    """Run the claim agent: process, status, history, reprocess, or metrics."""
    import os

    # Handle global options
    argv = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    options = [arg for arg in sys.argv[1:] if arg.startswith("--")]

    # Set log format from options
    if "--json" in options:
        os.environ["CLAIM_AGENT_LOG_FORMAT"] = "json"
    if "--debug" in options:
        os.environ["CLAIM_AGENT_LOG_LEVEL"] = "DEBUG"

    # Initialize logging
    _setup_logging()

    if not argv:
        print(_usage(), file=sys.stderr)
        sys.exit(1)

    first = argv[0].lower()

    # Commands that require a claim_id argument
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

    # Metrics command (optional claim_id)
    if first == "metrics":
        claim_id = argv[1] if len(argv) > 1 else None
        cmd_metrics(claim_id)
        return

    # Process command
    if first == "process":
        if len(argv) < 2:
            print("Error: process requires <claim.json>", file=sys.stderr)
            print(_usage(), file=sys.stderr)
            sys.exit(1)
        path = Path(argv[1])
        cmd_process(path)
        return

    # Legacy: single argument is a file path (process)
    path = Path(argv[0])
    if path.suffix and path.exists():
        cmd_process(path)
        return

    print(f"Error: Unknown command or file not found: {first}", file=sys.stderr)
    print(_usage(), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
