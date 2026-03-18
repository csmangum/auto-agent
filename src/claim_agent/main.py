"""CLI entry point for the claim agent.

This module provides the command-line interface with full observability:
- Structured logging with claim context
- Optional metrics reporting
- LangSmith tracing integration
"""

import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
import uvicorn
from pydantic import ValidationError

from claim_agent.config import get_settings
from claim_agent.config.settings import get_retention_period_years
from claim_agent.context import ClaimContext
from claim_agent.crews.main_crew import WORKFLOW_STAGES, run_claim_workflow
from claim_agent.workflow.handback_orchestrator import run_handback_workflow
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.db.database import get_db_path
from claim_agent.exceptions import ClaimAgentError
from claim_agent.models.claim import Attachment, ClaimInput
from claim_agent.observability import get_logger, get_metrics
from claim_agent.storage import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter
from claim_agent.utils import infer_attachment_type, sanitize_claim_data
from claim_agent.utils.sanitization import MAX_PAYOUT

# Ensure src is on path when run as script
if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

app = typer.Typer(
    name="claim-agent",
    help="Claim agent CLI: process claims, view status, manage review queue.",
    no_args_is_help=True,
)


def _get_cli_ctx() -> ClaimContext:
    """Shared context for CLI commands."""
    return ClaimContext.from_defaults(db_path=get_db_path())


def _usage() -> str:
    """Return usage string (for tests)."""
    return (
        "Usage: claim-agent [OPTIONS] COMMAND [ARGS]...\n\n"
        "Commands: serve, process, status, history, reprocess, metrics, review-queue, "
        "assign, approve, reject, request-info, escalate-siu, retention-enforce, "
        "dsar-access, dsar-deletion.\n"
        "Run claim-agent --help for full help."
    )


def _setup_logging(debug: bool = False, json_format: bool = False) -> None:
    """Configure logging for CLI usage."""
    if json_format:
        os.environ["CLAIM_AGENT_LOG_FORMAT"] = "json"
    if debug:
        os.environ["CLAIM_AGENT_LOG_LEVEL"] = "DEBUG"
    get_settings()  # Validate config at startup
    get_logger("claim_agent")
    logging.getLogger("claim_agent").setLevel(
        logging.DEBUG if debug else logging.INFO
    )


@app.callback()
def _global_options(
    ctx: typer.Context,
    debug: Annotated[bool, typer.Option("--debug", help="Enable debug logging")] = False,
    json_format: Annotated[bool, typer.Option("--json", help="Use JSON log format")] = False,
) -> None:
    """Global options applied before any command."""
    _setup_logging(debug=debug, json_format=json_format)
    from claim_agent.diary.auto_create import ensure_diary_listener_registered
    from claim_agent.events import ensure_webhook_listener_registered
    ensure_webhook_listener_registered()
    ensure_diary_listener_registered()


@app.command()
def serve(
    reload: Annotated[bool, typer.Option("--reload", help="Enable auto-reload for development")] = False,
    port: Annotated[int, typer.Option("--port", help="API server port")] = 8000,
    host: Annotated[str, typer.Option("--host", help="API server host")] = "0.0.0.0",
) -> None:
    """Start REST API server."""
    uvicorn.run(
        "claim_agent.api.server:app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def process(
    claim_path: Annotated[Path, typer.Argument(help="Path to claim JSON file")],
    attachment: Annotated[
        Optional[list[Path]],
        typer.Option("--attachment", "-a", help="Attach file (photo, PDF, estimate). May be repeated."),
    ] = None,
) -> None:
    """Process a new claim from a JSON file."""
    if not claim_path.exists():
        typer.echo(f"Error: File not found: {claim_path}", err=True)
        sys.exit(1)
    try:
        with open(claim_path, encoding="utf-8") as f:
            claim_data = json.load(f)
    except json.JSONDecodeError as e:
        typer.echo(f"Error: Invalid JSON in {claim_path}: {e}", err=True)
        sys.exit(1)
    try:
        ClaimInput.model_validate(claim_data)
    except ValidationError as e:
        typer.echo("Error: Invalid claim data:", err=True)
        typer.echo(e.json() if hasattr(e, "json") else str(e), err=True)
        sys.exit(1)

    sanitized = sanitize_claim_data(claim_data)
    claim_input = ClaimInput.model_validate(sanitized)
    ctx = _get_cli_ctx()
    repo = ctx.repo
    claim_id = repo.create_claim(claim_input)

    all_attachments = list(claim_input.attachments)
    if attachment:
        storage = get_storage_adapter()
        for ap in attachment:
            if not ap.exists():
                typer.echo(f"Warning: Attachment not found: {ap}", err=True)
                continue
            content = ap.read_bytes()
            stored_key = storage.save(claim_id=claim_id, filename=ap.name, content=content)
            url = storage.get_url(claim_id, stored_key)
            atype = infer_attachment_type(ap.name)
            all_attachments.append(
                Attachment(url=url, type=atype, description=f"Uploaded: {ap.name}")
            )
        if all_attachments:
            repo.update_claim_attachments(claim_id, all_attachments)

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

    claim_data_with_attachments = {**sanitized, "attachments": attachments_for_workflow}
    try:
        result = run_claim_workflow(claim_data_with_attachments, existing_claim_id=claim_id, ctx=ctx)
        typer.echo(json.dumps(result, indent=2))
    except Exception as e:
        typer.echo(f"Error: Claim processing failed: {e}", err=True)
        sys.exit(1)


@app.command()
def status(
    claim_id: Annotated[str, typer.Argument(help="Claim ID")],
) -> None:
    """Get claim status."""
    ctx = _get_cli_ctx()
    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        typer.echo(f"Error: Claim not found: {claim_id}", err=True)
        sys.exit(1)
    typer.echo(json.dumps(claim, indent=2))


@app.command()
def history(
    claim_id: Annotated[str, typer.Argument(help="Claim ID")],
) -> None:
    """Get claim audit log."""
    ctx = _get_cli_ctx()
    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        typer.echo(f"Error: Claim not found: {claim_id}", err=True)
        sys.exit(1)
    history, _ = ctx.repo.get_claim_history(claim_id)
    typer.echo(json.dumps(history, indent=2))


@app.command()
def reprocess(
    claim_id: Annotated[str, typer.Argument(help="Claim ID")],
    from_stage: Annotated[
        Optional[str],
        typer.Option("--from-stage", help="Resume from stage (router, escalation_check, workflow, settlement)"),
    ] = None,
) -> None:
    """Re-run workflow for an existing claim, optionally resuming from a stage."""
    if from_stage is not None and from_stage not in WORKFLOW_STAGES:
        typer.echo(
            f"Error: --from-stage must be one of {', '.join(WORKFLOW_STAGES)}",
            err=True,
        )
        sys.exit(1)

    ctx = _get_cli_ctx()
    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        typer.echo(f"Error: Claim not found: {claim_id}", err=True)
        sys.exit(1)
    claim_data = claim_data_from_row(claim)
    try:
        ClaimInput.model_validate(claim_data)
    except ValidationError as e:
        typer.echo("Error: Invalid claim data for reprocess:", err=True)
        typer.echo(e.json() if hasattr(e, "json") else str(e), err=True)
        sys.exit(1)

    resume_run_id: str | None = None
    if from_stage is not None:
        resume_run_id = ctx.repo.get_latest_checkpointed_run_id(claim_id)
        if resume_run_id is None:
            typer.echo(
                f"Warning: No prior checkpoints for {claim_id}; running full workflow.",
                err=True,
            )
            from_stage = None

    try:
        result = run_claim_workflow(
            claim_data,
            existing_claim_id=claim_id,
            resume_run_id=resume_run_id,
            from_stage=from_stage,
            ctx=ctx,
        )
        typer.echo(json.dumps(result, indent=2))
    except (ClaimAgentError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


@app.command("review-queue")
def review_queue(
    assignee: Annotated[Optional[str], typer.Option("--assignee", help="Filter by assignee")] = None,
    priority: Annotated[Optional[str], typer.Option("--priority", help="Filter by priority")] = None,
) -> None:
    """List claims needing review."""
    ctx = _get_cli_ctx()
    claims, total = ctx.repo.list_claims_needing_review(assignee=assignee, priority=priority)
    typer.echo(json.dumps({"claims": claims, "total": total}, indent=2))


@app.command()
def assign(
    claim_id: Annotated[str, typer.Argument(help="Claim ID")],
    assignee: Annotated[str, typer.Argument(help="Assignee ID")],
) -> None:
    """Assign claim to adjuster."""
    ctx = _get_cli_ctx()
    if ctx.repo.get_claim(claim_id) is None:
        typer.echo(f"Error: Claim not found: {claim_id}", err=True)
        sys.exit(1)
    try:
        ctx.adjuster_service.assign(claim_id, assignee, actor_id=ACTOR_WORKFLOW)
        typer.echo(json.dumps({"claim_id": claim_id, "assignee": assignee}, indent=2))
    except (ClaimAgentError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


@app.command()
def approve(
    claim_id: Annotated[str, typer.Argument(help="Claim ID")],
    confirmed_claim_type: Annotated[
        Optional[str],
        typer.Option("--confirmed-claim-type", help="Reviewer-confirmed claim type"),
    ] = None,
    confirmed_payout: Annotated[
        Optional[float],
        typer.Option("--confirmed-payout", help="Reviewer-confirmed payout amount"),
    ] = None,
    notes: Annotated[
        Optional[str],
        typer.Option("--notes", help="Reviewer notes for handback"),
    ] = None,
) -> None:
    """Approve claim and run Human Review Handback crew, then workflow (supervisor)."""
    ctx = _get_cli_ctx()
    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        typer.echo(f"Error: Claim not found: {claim_id}", err=True)
        sys.exit(1)
    claim_data = claim_data_from_row(claim)
    try:
        ClaimInput.model_validate(claim_data)
    except ValidationError as e:
        typer.echo("Error: Invalid claim data for reprocess:", err=True)
        typer.echo(e.json() if hasattr(e, "json") else str(e), err=True)
        sys.exit(1)
    try:
        if confirmed_payout is not None and (
            not math.isfinite(confirmed_payout) or confirmed_payout < 0 or confirmed_payout > MAX_PAYOUT
        ):
            typer.echo(
                f"Error: confirmed_payout must be 0 <= x <= {MAX_PAYOUT:,.0f}",
                err=True,
            )
            sys.exit(1)
        ctx.adjuster_service.approve(claim_id, actor_id=ACTOR_WORKFLOW)
        reviewer_decision = None
        if confirmed_claim_type is not None or confirmed_payout is not None or notes is not None:
            reviewer_decision = {
                "confirmed_claim_type": confirmed_claim_type,
                "confirmed_payout": confirmed_payout,
                "notes": notes,
            }
        result = run_handback_workflow(
            claim_id,
            reviewer_decision=reviewer_decision,
            actor_id=ACTOR_WORKFLOW,
            ctx=ctx,
        )
        typer.echo(json.dumps(result, indent=2))
    except (ClaimAgentError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


@app.command()
def reject(
    claim_id: Annotated[str, typer.Argument(help="Claim ID")],
    reason: Annotated[str, typer.Option("--reason", help="Rejection reason")] = "",
) -> None:
    """Reject claim."""
    ctx = _get_cli_ctx()
    if ctx.repo.get_claim(claim_id) is None:
        typer.echo(f"Error: Claim not found: {claim_id}", err=True)
        sys.exit(1)
    try:
        ctx.adjuster_service.reject(claim_id, actor_id=ACTOR_WORKFLOW, reason=reason)
        typer.echo(json.dumps({"claim_id": claim_id, "status": "denied"}, indent=2))
    except (ClaimAgentError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


@app.command("request-info")
def request_info(
    claim_id: Annotated[str, typer.Argument(help="Claim ID")],
    note: Annotated[str, typer.Option("--note", help="Note for request")] = "",
) -> None:
    """Request more information from claimant."""
    ctx = _get_cli_ctx()
    if ctx.repo.get_claim(claim_id) is None:
        typer.echo(f"Error: Claim not found: {claim_id}", err=True)
        sys.exit(1)
    try:
        ctx.adjuster_service.request_info(claim_id, actor_id=ACTOR_WORKFLOW, note=note)
        typer.echo(json.dumps({"claim_id": claim_id, "status": "pending_info"}, indent=2))
    except (ClaimAgentError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


@app.command("escalate-siu")
def escalate_siu(
    claim_id: Annotated[str, typer.Argument(help="Claim ID")],
) -> None:
    """Escalate claim to SIU."""
    ctx = _get_cli_ctx()
    if ctx.repo.get_claim(claim_id) is None:
        typer.echo(f"Error: Claim not found: {claim_id}", err=True)
        sys.exit(1)
    try:
        ctx.adjuster_service.escalate_to_siu(claim_id, actor_id=ACTOR_WORKFLOW)
        typer.echo(json.dumps({"claim_id": claim_id, "status": "under_investigation"}, indent=2))
    except (ClaimAgentError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)


@app.command("dsar-access")
def dsar_access(
    claimant_email: Annotated[str, typer.Option("--claimant-email", "-e", help="Claimant email or identifier")],
    claim_id: Annotated[Optional[str], typer.Option("--claim-id", "-c", help="Claim ID for verification")] = None,
    policy_number: Annotated[Optional[str], typer.Option("--policy", "-p", help="Policy number for verification")] = None,
    vin: Annotated[Optional[str], typer.Option("--vin", "-v", help="VIN for verification")] = None,
    fulfill: Annotated[bool, typer.Option("--fulfill", "-f", help="Fulfill the request immediately and output export")] = False,
) -> None:
    """Submit a DSAR access request (right-to-know). For testing/admin."""
    from claim_agent.services.dsar import fulfill_access_request, submit_access_request

    verification_data: dict = {}
    if claim_id:
        verification_data["claim_id"] = claim_id
    if policy_number:
        verification_data["policy_number"] = policy_number
    if vin:
        verification_data["vin"] = vin
    
    has_claim_id = bool(claim_id)
    has_both_policy_and_vin = bool(policy_number) and bool(vin)
    
    if not (has_claim_id or has_both_policy_and_vin):
        typer.echo("Error: Provide --claim-id or (--policy and --vin) for verification", err=True)
        raise typer.Exit(1)
    
    request_id = submit_access_request(
        claimant_identifier=claimant_email,
        verification_data=verification_data,
        actor_id="cli",
    )
    typer.echo(json.dumps({"request_id": request_id, "status": "pending"}, indent=2))
    if fulfill:
        try:
            export = fulfill_access_request(request_id, actor_id="cli")
            typer.echo("\nExport:")
            typer.echo(json.dumps(export, indent=2, default=str))
        except ValueError as e:
            typer.echo(f"Error fulfilling request: {e}", err=True)
            raise typer.Exit(1)


@app.command("dsar-deletion")
def dsar_deletion(
    claimant_email: Annotated[str, typer.Option("--claimant-email", "-e", help="Claimant email or identifier")],
    claim_id: Annotated[Optional[str], typer.Option("--claim-id", "-c", help="Claim ID for verification")] = None,
    policy_number: Annotated[Optional[str], typer.Option("--policy", "-p", help="Policy number for verification")] = None,
    vin: Annotated[Optional[str], typer.Option("--vin", "-v", help="VIN for verification")] = None,
    fulfill: Annotated[bool, typer.Option("--fulfill", "-f", help="Fulfill the request immediately")] = False,
) -> None:
    """Submit a DSAR deletion request (right-to-delete). Anonymizes PII, preserves audit trail."""
    from claim_agent.services.dsar import fulfill_deletion_request, submit_deletion_request

    verification_data: dict = {}
    if claim_id:
        verification_data["claim_id"] = claim_id
    if policy_number:
        verification_data["policy_number"] = policy_number
    if vin:
        verification_data["vin"] = vin
    
    has_claim_id = bool(claim_id)
    has_both_policy_and_vin = bool(policy_number) and bool(vin)
    
    if not (has_claim_id or has_both_policy_and_vin):
        typer.echo("Error: Provide --claim-id or (--policy and --vin) for verification", err=True)
        raise typer.Exit(1)
    
    request_id = submit_deletion_request(
        claimant_identifier=claimant_email,
        verification_data=verification_data,
        actor_id="cli",
    )
    typer.echo(json.dumps({"request_id": request_id, "status": "pending"}, indent=2))
    if fulfill:
        try:
            result = fulfill_deletion_request(request_id, actor_id="cli")
            typer.echo("\nResult:")
            typer.echo(json.dumps(result, indent=2))
        except ValueError as e:
            typer.echo(f"Error fulfilling request: {e}", err=True)
            raise typer.Exit(1)


@app.command("retention-enforce")
def retention_enforce(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be archived")] = False,
    years: Annotated[
        Optional[int],
        typer.Option("--years", "-y", help="Override retention period in years"),
    ] = None,
) -> None:
    """Archive claims older than retention period."""
    retention_years = years if years is not None else get_retention_period_years()
    ctx = _get_cli_ctx()
    repo = ctx.repo
    claims = repo.list_claims_for_retention(retention_years)

    if dry_run:
        typer.echo(json.dumps({
            "dry_run": True,
            "retention_period_years": retention_years,
            "claims_to_archive": len(claims),
            "claim_ids": [c["id"] for c in claims],
        }, indent=2))
        return

    archived = []
    failed = []
    for claim in claims:
        claim_id = claim["id"]
        try:
            repo.archive_claim(claim_id)
            archived.append(claim_id)
        except (ClaimAgentError, ValueError) as e:
            typer.echo(f"Warning: Could not archive {claim_id}: {e}", err=True)
            failed.append(claim_id)

    typer.echo(json.dumps({
        "retention_period_years": retention_years,
        "archived_count": len(archived),
        "archived_claim_ids": archived,
        "failed_count": len(failed),
        "failed_claim_ids": failed,
    }, indent=2))

    if failed:
        sys.exit(1)


@app.command("diary-escalate")
def diary_escalate(
    db_path: Annotated[
        Optional[str],
        typer.Option("--db", help="Path to claims database"),
    ] = None,
) -> None:
    """Run deadline escalation: notify overdue tasks, escalate to supervisor after threshold."""
    from claim_agent.diary.escalation import run_deadline_escalation

    result = run_deadline_escalation(db_path=db_path or get_db_path())
    typer.echo(json.dumps(result, indent=2))


@app.command("ucspa-deadlines")
def ucspa_deadlines(
    days_ahead: Annotated[
        int,
        typer.Option("--days", "-d", help="Days ahead to check for approaching deadlines"),
    ] = 3,
    dispatch_webhooks: Annotated[
        bool,
        typer.Option("--webhooks", "-w", help="Dispatch ucspa.deadline_approaching webhooks"),
    ] = True,
) -> None:
    """Check UCSPA deadlines and optionally dispatch webhook alerts for approaching deadlines."""
    from claim_agent.compliance.ucspa import claims_with_deadlines_approaching
    from claim_agent.notifications.webhook import dispatch_ucspa_deadline_approaching

    ctx = _get_cli_ctx()
    claims = claims_with_deadlines_approaching(ctx.repo, days_ahead=days_ahead)
    if dispatch_webhooks:
        for c in claims:
            dispatch_ucspa_deadline_approaching(
                c["claim_id"],
                c["deadline_type"],
                c["due_date"],
                c.get("loss_state"),
            )
    typer.echo(json.dumps({"days_ahead": days_ahead, "count": len(claims), "claims": claims}, indent=2))


@app.command()
def metrics(
    claim_id: Annotated[Optional[str], typer.Argument(help="Optional claim ID for per-claim metrics")] = None,
) -> None:
    """Display metrics for claims."""
    metrics_obj = get_metrics()

    if claim_id:
        summary = metrics_obj.get_claim_summary(claim_id)
        if summary is None:
            typer.echo(f"No metrics found for claim: {claim_id}", err=True)
            typer.echo("Note: Metrics are only available for claims processed in the current session.", err=True)
            sys.exit(1)
        typer.echo(json.dumps(summary.to_dict(), indent=2, default=str))
    else:
        global_stats = metrics_obj.get_global_stats()
        if global_stats["total_claims"] == 0:
            typer.echo("No claims have been processed in the current session.")
            typer.echo("Process some claims first to see metrics.")
            return
        typer.echo("Global Metrics Summary:")
        typer.echo(json.dumps(global_stats, indent=2, default=str))
        typer.echo("\nPer-Claim Summaries:")
        for summary in metrics_obj.get_all_summaries():
            typer.echo(f"\n  {summary.claim_id}:")
            typer.echo(f"    LLM Calls: {summary.total_llm_calls}")
            typer.echo(f"    Tokens: {summary.total_tokens}")
            typer.echo(f"    Cost: ${summary.total_cost_usd:.4f}")
            typer.echo(f"    Latency: {summary.total_latency_ms:.0f}ms (avg: {summary.avg_latency_ms:.0f}ms)")
            typer.echo(f"    Status: {summary.status}")


def _main() -> None:
    """Entry point: handle legacy file path, then invoke Typer app."""
    # Parse args to detect legacy file-path invocation
    args = sys.argv[1:]
    
    # Separate global options from other args and track actual positional args
    global_opts = []
    other_args = []
    positional = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--debug", "--json"):
            global_opts.append(arg)
            i += 1
        elif arg.startswith("--"):
            # Option that may have a value
            other_args.append(arg)
            i += 1
            # If next arg exists and doesn't start with --, it's the option value
            if i < len(args) and not args[i].startswith("-"):
                other_args.append(args[i])
                i += 1
        else:
            # Positional argument (not an option or option value)
            other_args.append(arg)
            positional.append(arg)
            i += 1
    
    # Legacy: single positional arg that looks like a file path
    if len(positional) == 1:
        path = Path(positional[0])
        if path.suffix and path.exists():
            # Transform to: [global_opts] + process <path> [command_opts]
            new_argv = global_opts + ["process"] + other_args
            sys.argv = [sys.argv[0]] + new_argv

    app()


def main() -> None:
    """Run the claim agent CLI."""
    _main()


# Exports for tests (cmd_* call into Typer command logic)
def cmd_process(claim_path: Path, attachment_paths: list[Path] | None = None) -> None:
    """Process a claim from a JSON file. Used by tests."""
    process(claim_path, attachment_paths)


def cmd_status(claim_id: str) -> None:
    """Print claim status. Used by tests."""
    status(claim_id)


def cmd_history(claim_id: str) -> None:
    """Print claim audit log. Used by tests."""
    history(claim_id)


def cmd_reprocess(claim_id: str, from_stage: str | None = None) -> None:
    """Re-run workflow for an existing claim. Used by tests."""
    reprocess(claim_id, from_stage)


def cmd_metrics(claim_id: str | None = None) -> None:
    """Display metrics for claims. Used by tests."""
    metrics(claim_id)


def cmd_retention_enforce(dry_run: bool = False, years: int | None = None) -> None:
    """Archive claims older than retention period. Used by tests."""
    retention_enforce(dry_run, years)


if __name__ == "__main__":
    main()
