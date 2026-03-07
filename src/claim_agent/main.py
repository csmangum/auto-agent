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
  claim-agent process <claim.json> [--attachment <file> ...]   Process a new claim
  claim-agent status <claim_id>      Get claim status
  claim-agent history <claim_id>     Get claim audit log
  claim-agent reprocess <claim_id>   Re-run workflow for an existing claim
  claim-agent metrics [claim_id]     Show metrics (optionally for specific claim)
  claim-agent review-queue [--assignee X] [--priority P]  List claims needing review
  claim-agent assign <claim_id> <assignee>   Assign claim to adjuster
  claim-agent approve <claim_id>     Approve and reprocess (supervisor)
  claim-agent reject <claim_id> [--reason "..."]   Reject claim
  claim-agent request-info <claim_id> [--note "..."]   Request more info
  claim-agent escalate-siu <claim_id>   Escalate to SIU
  claim-agent retention-enforce [--dry-run] [--years N]   Archive claims older than retention period
  claim-agent <claim.json>           Same as process (legacy)

Options:
  --attachment <file>                Attach file (photo, PDF, estimate). May be repeated.
  --assignee <id>                    Filter review queue by assignee
  --priority <level>                 Filter review queue by priority
  --reason <text>                    Rejection reason
  --note <text>                      Note for request-info
  --dry-run                          Show what would be archived without making changes (retention-enforce)
  --years <n>                        Override retention period in years (retention-enforce)
  --debug                            Enable debug logging
  --json                             Use JSON log format
"""


def _parse_opt_arg(name: str, default: str = "") -> str:
    """Parse --name value from sys.argv. Returns default if not found."""
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == name and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            return argv[i + 1]
    return default


def _parse_attachment_args() -> list[Path]:
    """Parse --attachment arguments from sys.argv."""
    attachment_paths = []
    raw = sys.argv[1:]
    i = 0
    while i < len(raw):
        if raw[i] == "--attachment" and i + 1 < len(raw):
            attachment_paths.append(Path(raw[i + 1]))
            i += 2
        else:
            i += 1
    return attachment_paths


def cmd_process(claim_path: Path, attachment_paths: list[Path] | None = None) -> None:
    """Process a claim from a JSON file, optionally with file attachments."""
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
    from claim_agent.db.database import get_db_path
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import Attachment
    from claim_agent.storage import get_storage_adapter
    from claim_agent.storage.local import LocalStorageAdapter
    from claim_agent.utils import infer_attachment_type, sanitize_claim_data

    sanitized = sanitize_claim_data(claim_data)
    claim_input = ClaimInput.model_validate(sanitized)
    repo = ClaimRepository(db_path=get_db_path())
    claim_id = repo.create_claim(claim_input)

    all_attachments = list(claim_input.attachments)
    if attachment_paths:
        storage = get_storage_adapter()
        for ap in attachment_paths:
            if not ap.exists():
                print(f"Warning: Attachment not found: {ap}", file=sys.stderr)
                continue
            content = ap.read_bytes()
            stored_key = storage.save(
                claim_id=claim_id,
                filename=ap.name,
                content=content,
            )
            url = storage.get_url(claim_id, stored_key)
            atype = infer_attachment_type(ap.name)
            all_attachments.append(
                Attachment(url=url, type=atype, description=f"Uploaded: {ap.name}")
            )
        if all_attachments:
            repo.update_claim_attachments(claim_id, all_attachments)

    # Use file:// URLs for local storage so vision tool can read
    storage = get_storage_adapter()
    attachments_for_workflow = []
    for a in all_attachments:
        url = a.url
        if isinstance(storage, LocalStorageAdapter) and url and not url.startswith(
            ("http://", "https://", "file://")
        ):
            path = storage.get_path(claim_id, url)
            if path.exists():
                url = f"file://{path.resolve()}"
        attachments_for_workflow.append({**a.model_dump(mode="json"), "url": url})

    claim_data_with_attachments = {
        **sanitized,
        "attachments": attachments_for_workflow,
    }
    try:
        result = run_claim_workflow(claim_data_with_attachments, existing_claim_id=claim_id)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: Claim processing failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status(claim_id: str) -> None:
    """Print claim status."""
    from claim_agent.db.database import get_db_path
    from claim_agent.db.repository import ClaimRepository

    repo = ClaimRepository(db_path=get_db_path())
    claim = repo.get_claim(claim_id)
    if claim is None:
        print(f"Error: Claim not found: {claim_id}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(claim, indent=2))


def cmd_history(claim_id: str) -> None:
    """Print claim audit log."""
    from claim_agent.db.database import get_db_path
    from claim_agent.db.repository import ClaimRepository

    repo = ClaimRepository(db_path=get_db_path())
    claim = repo.get_claim(claim_id)
    if claim is None:
        print(f"Error: Claim not found: {claim_id}", file=sys.stderr)
        sys.exit(1)
    history = repo.get_claim_history(claim_id)
    print(json.dumps(history, indent=2))


def cmd_reprocess(claim_id: str) -> None:
    """Re-run workflow for an existing claim."""
    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.claim_data import claim_data_from_row
    from claim_agent.db.database import get_db_path
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput

    repo = ClaimRepository(db_path=get_db_path())
    claim = repo.get_claim(claim_id)
    if claim is None:
        print(f"Error: Claim not found: {claim_id}", file=sys.stderr)
        sys.exit(1)
    claim_data = claim_data_from_row(claim)
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


def cmd_review_queue(assignee: str | None = None, priority: str | None = None) -> None:
    """List claims needing review."""
    from claim_agent.db.database import get_db_path
    from claim_agent.db.repository import ClaimRepository

    repo = ClaimRepository(db_path=get_db_path())
    claims, total = repo.list_claims_needing_review(
        assignee=assignee,
        priority=priority,
    )
    print(json.dumps({"claims": claims, "total": total}, indent=2))


def cmd_assign(claim_id: str, assignee: str) -> None:
    """Assign claim to adjuster."""
    from claim_agent.db.audit_events import ACTOR_WORKFLOW
    from claim_agent.db.database import get_db_path
    from claim_agent.db.repository import ClaimRepository

    repo = ClaimRepository(db_path=get_db_path())
    if repo.get_claim(claim_id) is None:
        print(f"Error: Claim not found: {claim_id}", file=sys.stderr)
        sys.exit(1)
    try:
        repo.assign_claim(claim_id, assignee, actor_id=ACTOR_WORKFLOW)
        print(json.dumps({"claim_id": claim_id, "assignee": assignee}, indent=2))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_approve(claim_id: str) -> None:
    """Approve claim and re-run workflow."""
    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.audit_events import ACTOR_WORKFLOW
    from claim_agent.db.claim_data import claim_data_from_row
    from claim_agent.db.database import get_db_path
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput

    repo = ClaimRepository(db_path=get_db_path())
    claim = repo.get_claim(claim_id)
    if claim is None:
        print(f"Error: Claim not found: {claim_id}", file=sys.stderr)
        sys.exit(1)
    claim_data = claim_data_from_row(claim)
    try:
        ClaimInput.model_validate(claim_data)
    except ValidationError as e:
        print("Error: Invalid claim data for reprocess:", file=sys.stderr)
        print(e.json() if hasattr(e, "json") else str(e), file=sys.stderr)
        sys.exit(1)
    try:
        repo.perform_adjuster_action(claim_id, "approve", actor_id=ACTOR_WORKFLOW)
        result = run_claim_workflow(
            claim_data,
            existing_claim_id=claim_id,
            actor_id=ACTOR_WORKFLOW,
        )
        print(json.dumps(result, indent=2))
    except (ValueError, Exception) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_reject(claim_id: str, reason: str = "") -> None:
    """Reject claim."""
    from claim_agent.db.audit_events import ACTOR_WORKFLOW
    from claim_agent.db.database import get_db_path
    from claim_agent.db.repository import ClaimRepository

    repo = ClaimRepository(db_path=get_db_path())
    if repo.get_claim(claim_id) is None:
        print(f"Error: Claim not found: {claim_id}", file=sys.stderr)
        sys.exit(1)
    try:
        repo.perform_adjuster_action(claim_id, "reject", actor_id=ACTOR_WORKFLOW, reason=reason)
        print(json.dumps({"claim_id": claim_id, "status": "denied"}, indent=2))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_request_info(claim_id: str, note: str = "") -> None:
    """Request more information from claimant."""
    from claim_agent.db.audit_events import ACTOR_WORKFLOW
    from claim_agent.db.database import get_db_path
    from claim_agent.db.repository import ClaimRepository

    repo = ClaimRepository(db_path=get_db_path())
    if repo.get_claim(claim_id) is None:
        print(f"Error: Claim not found: {claim_id}", file=sys.stderr)
        sys.exit(1)
    try:
        repo.perform_adjuster_action(claim_id, "request_info", actor_id=ACTOR_WORKFLOW, note=note)
        print(json.dumps({"claim_id": claim_id, "status": "pending_info"}, indent=2))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_escalate_siu(claim_id: str) -> None:
    """Escalate claim to SIU."""
    from claim_agent.db.audit_events import ACTOR_WORKFLOW
    from claim_agent.db.database import get_db_path
    from claim_agent.db.repository import ClaimRepository

    repo = ClaimRepository(db_path=get_db_path())
    if repo.get_claim(claim_id) is None:
        print(f"Error: Claim not found: {claim_id}", file=sys.stderr)
        sys.exit(1)
    try:
        repo.perform_adjuster_action(claim_id, "escalate_to_siu", actor_id=ACTOR_WORKFLOW)
        print(json.dumps({"claim_id": claim_id, "status": "under_investigation"}, indent=2))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_retention_enforce(dry_run: bool = False, years: int | None = None) -> None:
    """Archive claims older than retention period. Logs actions to audit."""
    from claim_agent.config.settings import get_retention_period_years
    from claim_agent.db.database import get_db_path
    from claim_agent.db.repository import ClaimRepository

    retention_years = years if years is not None else get_retention_period_years()
    repo = ClaimRepository(db_path=get_db_path())
    claims = repo.list_claims_for_retention(retention_years)

    if dry_run:
        print(json.dumps({
            "dry_run": True,
            "retention_period_years": retention_years,
            "claims_to_archive": len(claims),
            "claim_ids": [c["id"] for c in claims],
        }, indent=2))
        return

    archived = []
    for claim in claims:
        claim_id = claim["id"]
        try:
            repo.archive_claim(claim_id)
            archived.append(claim_id)
        except ValueError as e:
            print(f"Warning: Could not archive {claim_id}: {e}", file=sys.stderr)

    print(json.dumps({
        "retention_period_years": retention_years,
        "archived_count": len(archived),
        "archived_claim_ids": archived,
    }, indent=2))


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

    # Review queue command
    if first == "review-queue":
        assignee = _parse_opt_arg("--assignee") or None
        priority = _parse_opt_arg("--priority") or None
        cmd_review_queue(assignee=assignee, priority=priority)
        return

    # Assign command (claim_id, assignee)
    if first == "assign":
        if len(argv) < 3:
            print("Error: assign requires <claim_id> <assignee>", file=sys.stderr)
            print(_usage(), file=sys.stderr)
            sys.exit(1)
        cmd_assign(argv[1], argv[2])
        return

    # Adjuster action commands (claim_id required)
    if first in ("approve", "reject", "request-info", "escalate-siu"):
        if len(argv) < 2:
            print(f"Error: {first} requires <claim_id>", file=sys.stderr)
            print(_usage(), file=sys.stderr)
            sys.exit(1)
        claim_id = argv[1]
        if first == "approve":
            cmd_approve(claim_id)
        elif first == "reject":
            cmd_reject(claim_id, reason=_parse_opt_arg("--reason"))
        elif first == "request-info":
            cmd_request_info(claim_id, note=_parse_opt_arg("--note"))
        else:
            cmd_escalate_siu(claim_id)
        return

    # Metrics command (optional claim_id)
    if first == "metrics":
        claim_id = argv[1] if len(argv) > 1 else None
        cmd_metrics(claim_id)
        return

    # Retention enforce command
    if first == "retention-enforce":
        dry_run = "--dry-run" in options
        years_arg = _parse_opt_arg("--years")
        years = None
        if years_arg:
            try:
                years = int(years_arg)
            except ValueError:
                print("Error: --years must be an integer", file=sys.stderr)
                print(_usage(), file=sys.stderr)
                sys.exit(1)
            if years <= 0:
                print("Error: --years must be a positive integer", file=sys.stderr)
                print(_usage(), file=sys.stderr)
                sys.exit(1)
        cmd_retention_enforce(dry_run=dry_run, years=years)
        return

    # Process command
    if first == "process":
        if len(argv) < 2:
            print("Error: process requires <claim.json>", file=sys.stderr)
            print(_usage(), file=sys.stderr)
            sys.exit(1)
        path = Path(argv[1])
        attachment_paths = _parse_attachment_args()
        cmd_process(path, attachment_paths if attachment_paths else None)
        return

    # Legacy: single argument is a file path (process)
    path = Path(argv[0])
    if path.suffix and path.exists():
        attachment_paths = _parse_attachment_args()
        cmd_process(path, attachment_paths if attachment_paths else None)
        return

    print(f"Error: Unknown command or file not found: {first}", file=sys.stderr)
    print(_usage(), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
