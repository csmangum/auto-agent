"""CLI entry point for the claim agent.

This module provides the command-line interface with full observability:
- Structured logging with claim context
- Optional metrics reporting
- LangSmith tracing integration
"""

import asyncio
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Optional

import typer
import uvicorn
from pydantic import ValidationError

from claim_agent.config import get_settings
from claim_agent.config.settings import (
    get_audit_log_retention_years_after_purge,
    get_purge_after_archive_by_state,
    get_retention_by_state,
    get_retention_period_years,
    get_retention_purge_after_archive_years,
    is_audit_log_purge_enabled,
)
from claim_agent.context import ClaimContext
from claim_agent.crews.main_crew import WORKFLOW_STAGES, run_claim_workflow
from claim_agent.workflow.handback_orchestrator import run_handback_workflow
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.db.database import get_db_path
from claim_agent.services.document_retention import run_document_retention_enforce
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


def _resolve_audit_log_retention_years(years_opt: Optional[int]) -> int:
    """Return years after purged_at for audit tooling, or exit if unset."""
    y = years_opt if years_opt is not None else get_audit_log_retention_years_after_purge()
    if y is None:
        typer.echo(
            "Error: set AUDIT_LOG_RETENTION_YEARS_AFTER_PURGE or pass --years",
            err=True,
        )
        raise typer.Exit(1)
    return y


def _write_eligible_claim_ids_file(path: Path, claim_ids: list[str]) -> None:
    """Write one claim ID per line for large eligibility sets (avoid huge stdout JSON)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for cid in claim_ids:
            f.write(f"{cid}\n")


def _usage() -> str:
    """Return usage string (for tests)."""
    return (
        "Usage: claim-agent [OPTIONS] COMMAND [ARGS]...\n\n"
        "Commands: serve, process, status, history, reprocess, metrics, review-queue, "
        "assign, approve, reject, request-info, escalate-siu, retention-enforce, "
        "document-retention-enforce, retention-purge, retention-report, audit-log-export, audit-log-purge, "
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
    logging.getLogger("claim_agent").setLevel(logging.DEBUG if debug else logging.INFO)


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
    reload: Annotated[
        bool, typer.Option("--reload", help="Enable auto-reload for development")
    ] = False,
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
        typer.Option(
            "--attachment", "-a", help="Attach file (photo, PDF, estimate). May be repeated."
        ),
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
        if (
            isinstance(storage, LocalStorageAdapter)
            and url
            and not url.startswith(("http://", "https://", "file://"))
        ):
            path = storage.get_path(claim_id, url)
            if path.exists():
                url = f"file://{path.resolve()}"
        attachments_for_workflow.append({**a.model_dump(mode="json"), "url": url})

    claim_data_with_attachments = {**sanitized, "attachments": attachments_for_workflow}
    try:
        result = run_claim_workflow(
            claim_data_with_attachments, existing_claim_id=claim_id, ctx=ctx
        )
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
        typer.Option("--from-stage", help=f"Resume from stage ({', '.join(WORKFLOW_STAGES)})"),
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
    assignee: Annotated[
        Optional[str], typer.Option("--assignee", help="Filter by assignee")
    ] = None,
    priority: Annotated[
        Optional[str], typer.Option("--priority", help="Filter by priority")
    ] = None,
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
            not math.isfinite(confirmed_payout)
            or confirmed_payout < 0
            or confirmed_payout > MAX_PAYOUT
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
    claimant_email: Annotated[
        str, typer.Option("--claimant-email", "-e", help="Claimant email or identifier")
    ],
    claim_id: Annotated[
        Optional[str], typer.Option("--claim-id", "-c", help="Claim ID for verification")
    ] = None,
    policy_number: Annotated[
        Optional[str], typer.Option("--policy", "-p", help="Policy number for verification")
    ] = None,
    vin: Annotated[Optional[str], typer.Option("--vin", "-v", help="VIN for verification")] = None,
    fulfill: Annotated[
        bool,
        typer.Option("--fulfill", "-f", help="Fulfill the request immediately and output export"),
    ] = False,
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
    claimant_email: Annotated[
        str, typer.Option("--claimant-email", "-e", help="Claimant email or identifier")
    ],
    claim_id: Annotated[
        Optional[str], typer.Option("--claim-id", "-c", help="Claim ID for verification")
    ] = None,
    policy_number: Annotated[
        Optional[str], typer.Option("--policy", "-p", help="Policy number for verification")
    ] = None,
    vin: Annotated[Optional[str], typer.Option("--vin", "-v", help="VIN for verification")] = None,
    fulfill: Annotated[
        bool, typer.Option("--fulfill", "-f", help="Fulfill the request immediately")
    ] = False,
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
    include_litigation_hold: Annotated[
        bool,
        typer.Option(
            "--include-litigation-hold",
            help="Archive claims with litigation hold (default: exclude)",
        ),
    ] = False,
) -> None:
    """Archive claims older than retention period. Skips litigation hold claims by default."""
    retention_years = years if years is not None else get_retention_period_years()
    retention_by_state = get_retention_by_state() if years is None else None
    ctx = _get_cli_ctx()
    repo = ctx.repo
    claims = repo.list_claims_for_retention(
        retention_years,
        retention_by_state=retention_by_state,
        exclude_litigation_hold=not include_litigation_hold,
    )

    if dry_run:
        typer.echo(
            json.dumps(
                {
                    "dry_run": True,
                    "retention_period_years": retention_years,
                    "claims_to_archive": len(claims),
                    "claim_ids": [c["id"] for c in claims],
                },
                indent=2,
            )
        )
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

    typer.echo(
        json.dumps(
            {
                "retention_period_years": retention_years,
                "archived_count": len(archived),
                "archived_claim_ids": archived,
                "failed_count": len(failed),
                "failed_claim_ids": failed,
            },
            indent=2,
        )
    )

    if failed:
        sys.exit(1)


@app.command("document-retention-enforce")
def document_retention_enforce(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="List documents that would be soft-archived"),
    ] = False,
    as_of: Annotated[
        Optional[str],
        typer.Option(
            "--as-of",
            help="Cutoff date YYYY-MM-DD (default: today UTC); documents with retention_date before this are eligible",
        ),
    ] = None,
) -> None:
    """Soft-archive claim documents past ``retention_date`` (separate from claim retention).

    Sets ``retention_enforced_at`` on each row and appends ``document_retention_enforced``
    to ``claim_audit_log``. Schedule with cron alongside ``retention-enforce`` as needed.
    Does not delete files or remove rows.
    """
    if as_of is not None:
        cutoff = as_of
        try:
            datetime.strptime(cutoff, "%Y-%m-%d")
        except ValueError:
            typer.echo("Error: --as-of must be a valid calendar date YYYY-MM-DD", err=True)
            raise typer.Exit(1)
    else:
        cutoff = datetime.now(timezone.utc).date().isoformat()
    result = run_document_retention_enforce(
        db_path=get_db_path(),
        cutoff_date=cutoff,
        dry_run=dry_run,
    )
    typer.echo(json.dumps(result, indent=2))
    if not dry_run and result.get("failed_count"):
        sys.exit(1)


@app.command("retention-purge")
def retention_purge(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be purged")] = False,
    years: Annotated[
        Optional[int],
        typer.Option(
            "--years",
            "-y",
            help="Override years after archive before purge (default from settings)",
        ),
    ] = None,
    include_litigation_hold: Annotated[
        bool,
        typer.Option("--include-litigation-hold", help="Purge claims with litigation hold"),
    ] = False,
    export_before_purge: Annotated[
        bool,
        typer.Option(
            "--export-before-purge",
            help=(
                "Export each claim to S3/Glacier cold storage before anonymising. "
                "Requires RETENTION_EXPORT_ENABLED=true and RETENTION_EXPORT_S3_BUCKET."
            ),
        ),
    ] = False,
) -> None:
    """Purge archived claims past purge horizon (anonymize PII, status purged)."""
    purge_years = years if years is not None else get_retention_purge_after_archive_years()
    purge_by_state = get_purge_after_archive_by_state() if years is None else None
    ctx = _get_cli_ctx()
    repo = ctx.repo
    claims = repo.list_claims_for_purge(
        purge_years,
        purge_by_state=purge_by_state,
        exclude_litigation_hold=not include_litigation_hold,
    )

    purge_state_info: dict[str, Any] = {}
    if purge_by_state:
        purge_state_info["purge_by_state"] = purge_by_state

    if dry_run:
        typer.echo(
            json.dumps(
                {
                    "dry_run": True,
                    "purge_after_archive_years": purge_years,
                    **purge_state_info,
                    "claims_to_purge": len(claims),
                    "claim_ids": [c["id"] for c in claims],
                },
                indent=2,
            )
        )
        return

    export_cfg = None
    if export_before_purge:
        export_cfg = get_settings().retention_export
        if not export_cfg.enabled:
            typer.echo(
                "Error: --export-before-purge requires RETENTION_EXPORT_ENABLED=true", err=True
            )
            raise typer.Exit(1)
        if not export_cfg.s3_bucket:
            typer.echo(
                "Error: --export-before-purge requires RETENTION_EXPORT_S3_BUCKET to be set",
                err=True,
            )
            raise typer.Exit(1)

    purged: list[str] = []
    failed: list[str] = []
    exported: list[str] = []
    export_failed: list[str] = []
    for claim in claims:
        claim_id = claim["id"]
        if export_cfg is not None:
            from claim_agent.storage.export import export_claim_to_cold_storage

            try:
                export_claim_to_cold_storage(claim_id, repo, export_cfg)
                exported.append(claim_id)
            except Exception as e:
                typer.echo(
                    f"Warning: Could not export {claim_id} before purge: {e}", err=True
                )
                export_failed.append(claim_id)
                failed.append(claim_id)
                continue
        try:
            repo.purge_claim(claim_id)
            purged.append(claim_id)
        except (ClaimAgentError, ValueError) as e:
            typer.echo(f"Warning: Could not purge {claim_id}: {e}", err=True)
            failed.append(claim_id)

    result: dict[str, Any] = {
        "purge_after_archive_years": purge_years,
        **purge_state_info,
        "purged_count": len(purged),
        "purged_claim_ids": purged,
        "failed_count": len(failed),
        "failed_claim_ids": failed,
    }
    if export_before_purge:
        result["exported_count"] = len(exported)
        result["exported_claim_ids"] = exported
        result["export_failed_count"] = len(export_failed)
        result["export_failed_claim_ids"] = export_failed

    typer.echo(json.dumps(result, indent=2))

    if failed:
        sys.exit(1)


@app.command("retention-export")
def retention_export(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be exported without uploading"),
    ] = False,
    years: Annotated[
        Optional[int],
        typer.Option(
            "--years",
            "-y",
            help="Override years after archive before export (default from settings)",
        ),
    ] = None,
    include_litigation_hold: Annotated[
        bool,
        typer.Option("--include-litigation-hold", help="Export claims with litigation hold"),
    ] = False,
) -> None:
    """Export archived claims to S3/Glacier cold storage before purge.

    Eligible claims are those past the purge horizon that have not yet been
    exported (idempotent: already-exported claims are skipped).

    Requires ``RETENTION_EXPORT_ENABLED=true`` and ``RETENTION_EXPORT_S3_BUCKET``
    to be configured (unless ``--dry-run``).
    """
    purge_years = years if years is not None else get_retention_purge_after_archive_years()
    purge_by_state = get_purge_after_archive_by_state() if years is None else None
    ctx = _get_cli_ctx()
    repo = ctx.repo
    claims = repo.list_claims_for_export(
        purge_years,
        purge_by_state=purge_by_state,
        exclude_litigation_hold=not include_litigation_hold,
    )

    purge_state_info: dict[str, Any] = {}
    if purge_by_state:
        purge_state_info["purge_by_state"] = purge_by_state

    if dry_run:
        typer.echo(
            json.dumps(
                {
                    "dry_run": True,
                    "purge_after_archive_years": purge_years,
                    **purge_state_info,
                    "claims_to_export": len(claims),
                    "claim_ids": [c["id"] for c in claims],
                },
                indent=2,
            )
        )
        return

    export_cfg = get_settings().retention_export
    if not export_cfg.enabled:
        typer.echo(
            "Error: RETENTION_EXPORT_ENABLED must be true to run retention-export", err=True
        )
        raise typer.Exit(1)
    if not export_cfg.s3_bucket:
        typer.echo(
            "Error: RETENTION_EXPORT_S3_BUCKET must be set to run retention-export", err=True
        )
        raise typer.Exit(1)

    from claim_agent.storage.export import export_claim_to_cold_storage

    exported: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    for claim in claims:
        claim_id = claim["id"]
        if claim.get("cold_storage_exported_at"):
            skipped.append(claim_id)
            continue
        try:
            export_claim_to_cold_storage(claim_id, repo, export_cfg)
            exported.append(claim_id)
        except Exception as e:
            typer.echo(f"Warning: Could not export {claim_id}: {e}", err=True)
            failed.append(claim_id)

    typer.echo(
        json.dumps(
            {
                "purge_after_archive_years": purge_years,
                **purge_state_info,
                "exported_count": len(exported),
                "exported_claim_ids": exported,
                "skipped_already_exported": len(skipped),
                "failed_count": len(failed),
                "failed_claim_ids": failed,
            },
            indent=2,
        )
    )

    if failed:
        sys.exit(1)


@app.command("retention-report")
def retention_report(
    years: Annotated[
        Optional[int],
        typer.Option("--years", "-y", help="Override retention period in years"),
    ] = None,
    purge_years: Annotated[
        Optional[int],
        typer.Option(
            "--purge-years",
            help="Override years after archive before purge (for pending_purge count)",
        ),
    ] = None,
    audit_purge_years: Annotated[
        Optional[int],
        typer.Option(
            "--audit-purge-years",
            help="Years after purged_at for audit eligibility counts (overrides env)",
        ),
    ] = None,
    include_litigation_hold_audit: Annotated[
        bool,
        typer.Option(
            "--include-litigation-hold-audit",
            help="Include litigation-hold claims in audit eligibility counts",
        ),
    ] = False,
) -> None:
    """Produce retention audit report: tier/status counts, litigation hold, pending archive/purge."""
    retention_years = years if years is not None else get_retention_period_years()
    retention_by_state = get_retention_by_state() if years is None else None
    purge_after = (
        purge_years if purge_years is not None else get_retention_purge_after_archive_years()
    )
    purge_by_state = get_purge_after_archive_by_state() if purge_years is None else None
    audit_years_effective = (
        audit_purge_years
        if audit_purge_years is not None
        else get_audit_log_retention_years_after_purge()
    )
    ctx = _get_cli_ctx()
    report = ctx.repo.retention_report(
        retention_years,
        retention_by_state=retention_by_state,
        purge_after_archive_years=purge_after,
        purge_by_state=purge_by_state,
        audit_log_retention_years_after_purge=audit_years_effective,
        exclude_litigation_hold_from_audit_eligibility=not include_litigation_hold_audit,
    )
    typer.echo(json.dumps(report, indent=2))


@app.command("audit-log-export")
def audit_log_export(
    output: Annotated[Path, typer.Option("--output", "-o", help="NDJSON output file path")],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print counts only; do not write a file"),
    ] = False,
    years: Annotated[
        Optional[int],
        typer.Option(
            "--years",
            "-y",
            help="Years after purged_at (overrides AUDIT_LOG_RETENTION_YEARS_AFTER_PURGE)",
        ),
    ] = None,
    include_litigation_hold: Annotated[
        bool,
        typer.Option(
            "--include-litigation-hold",
            help="Include claims with litigation hold",
        ),
    ] = False,
    print_eligible_claim_ids: Annotated[
        bool,
        typer.Option(
            "--print-eligible-claim-ids",
            help="Include full eligible claim ID list in dry-run JSON (can be very large)",
        ),
    ] = False,
    eligible_claim_ids_file: Annotated[
        Optional[Path],
        typer.Option(
            "--eligible-claim-ids-file",
            help="Write one eligible claim ID per line (after eligibility is computed)",
        ),
    ] = None,
) -> None:
    """Export claim_audit_log rows for purged claims past the audit retention horizon (NDJSON)."""
    audit_years = _resolve_audit_log_retention_years(years)
    ctx = _get_cli_ctx()
    repo = ctx.repo
    eligible = repo.list_claim_ids_eligible_for_audit_log_retention(
        audit_years,
        exclude_litigation_hold=not include_litigation_hold,
    )
    row_count = repo.count_audit_log_rows_for_claim_ids(eligible)
    if eligible_claim_ids_file is not None:
        _write_eligible_claim_ids_file(eligible_claim_ids_file, eligible)
    if dry_run:
        payload: dict[str, Any] = {
            "dry_run": True,
            "audit_retention_years_after_purge": audit_years,
            "eligible_claim_count": len(eligible),
            "audit_row_count": row_count,
        }
        if eligible_claim_ids_file is not None:
            payload["eligible_claim_ids_file"] = str(eligible_claim_ids_file)
        if print_eligible_claim_ids:
            payload["eligible_claim_ids"] = eligible
        typer.echo(json.dumps(payload, indent=2))
        return
    rows = repo.fetch_audit_log_rows_for_claim_ids(eligible)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
    summary: dict[str, Any] = {
        "output": str(output),
        "audit_retention_years_after_purge": audit_years,
        "eligible_claim_count": len(eligible),
        "audit_row_count": len(rows),
    }
    if eligible_claim_ids_file is not None:
        summary["eligible_claim_ids_file"] = str(eligible_claim_ids_file)
    typer.echo(json.dumps(summary, indent=2))


@app.command("audit-log-purge")
def audit_log_purge(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be deleted; no deletes"),
    ] = False,
    years: Annotated[
        Optional[int],
        typer.Option(
            "--years",
            "-y",
            help="Years after purged_at (overrides AUDIT_LOG_RETENTION_YEARS_AFTER_PURGE)",
        ),
    ] = None,
    include_litigation_hold: Annotated[
        bool,
        typer.Option(
            "--include-litigation-hold",
            help="Include claims with litigation hold",
        ),
    ] = False,
    ack_exported: Annotated[
        bool,
        typer.Option(
            "--ack-exported",
            help="Required: confirm audit rows were exported to cold storage",
        ),
    ] = False,
    print_eligible_claim_ids: Annotated[
        bool,
        typer.Option(
            "--print-eligible-claim-ids",
            help="Include full eligible claim ID list in dry-run JSON (can be very large)",
        ),
    ] = False,
    eligible_claim_ids_file: Annotated[
        Optional[Path],
        typer.Option(
            "--eligible-claim-ids-file",
            help="Write one eligible claim ID per line (after eligibility is computed)",
        ),
    ] = None,
) -> None:
    """Delete claim_audit_log rows for eligible purged claims (requires env gate + --ack-exported)."""
    audit_years = _resolve_audit_log_retention_years(years)
    ctx = _get_cli_ctx()
    repo = ctx.repo
    eligible = repo.list_claim_ids_eligible_for_audit_log_retention(
        audit_years,
        exclude_litigation_hold=not include_litigation_hold,
    )
    row_count = repo.count_audit_log_rows_for_claim_ids(eligible)
    if eligible_claim_ids_file is not None:
        _write_eligible_claim_ids_file(eligible_claim_ids_file, eligible)
    if dry_run:
        payload: dict[str, Any] = {
            "dry_run": True,
            "audit_retention_years_after_purge": audit_years,
            "eligible_claim_count": len(eligible),
            "audit_row_count": row_count,
            "audit_log_purge_enabled": is_audit_log_purge_enabled(),
        }
        if eligible_claim_ids_file is not None:
            payload["eligible_claim_ids_file"] = str(eligible_claim_ids_file)
        if print_eligible_claim_ids:
            payload["eligible_claim_ids"] = eligible
        typer.echo(json.dumps(payload, indent=2))
        return
    if not ack_exported:
        typer.echo(
            "Error: pass --ack-exported after exporting audit rows to cold storage", err=True
        )
        raise typer.Exit(1)
    if not is_audit_log_purge_enabled():
        typer.echo(
            "Error: set AUDIT_LOG_PURGE_ENABLED=true after compliance approval",
            err=True,
        )
        raise typer.Exit(1)
    deleted = repo.purge_audit_log_for_claim_ids(
        eligible,
        audit_purge_enabled=is_audit_log_purge_enabled(),
    )
    summary: dict[str, Any] = {
        "audit_retention_years_after_purge": audit_years,
        "eligible_claim_count": len(eligible),
        "deleted_audit_row_count": deleted,
    }
    if eligible_claim_ids_file is not None:
        summary["eligible_claim_ids_file"] = str(eligible_claim_ids_file)
    typer.echo(json.dumps(summary, indent=2))


@app.command("litigation-hold")
def litigation_hold(
    claim_id: Annotated[str, typer.Option("--claim-id", "-c", help="Claim ID")],
    on: Annotated[bool, typer.Option("--on", help="Set litigation hold")] = False,
    off: Annotated[bool, typer.Option("--off", help="Clear litigation hold")] = False,
) -> None:
    """Set or clear litigation hold on a claim. Hold suspends retention and DSAR deletion."""
    if on == off:
        typer.echo("Error: Specify exactly one of --on or --off", err=True)
        raise typer.Exit(1)
    ctx = _get_cli_ctx()
    try:
        ctx.repo.set_litigation_hold(claim_id, on, actor_id="cli")
    except ClaimAgentError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps({"claim_id": claim_id, "litigation_hold": on}, indent=2))


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
    typer.echo(
        json.dumps({"days_ahead": days_ahead, "count": len(claims), "claims": claims}, indent=2)
    )


@app.command("run-scheduler")
def run_scheduler() -> None:
    """Run in-process scheduler in foreground (for dedicated scheduler process)."""
    from claim_agent.scheduler import ensure_scheduler_running, stop_scheduler

    if not get_settings().scheduler.enabled:
        typer.echo(
            "SCHEDULER_ENABLED is false. Set SCHEDULER_ENABLED=true to run in-process scheduler.",
            err=True,
        )
        raise typer.Exit(1)

    ensure_scheduler_running()
    typer.echo("In-process scheduler started. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(stop_scheduler())
        typer.echo("Scheduler stopped.")


@app.command()
def metrics(
    claim_id: Annotated[
        Optional[str], typer.Argument(help="Optional claim ID for per-claim metrics")
    ] = None,
) -> None:
    """Display metrics for claims."""
    metrics_obj = get_metrics()

    if claim_id:
        summary = metrics_obj.get_claim_summary(claim_id)
        if summary is None:
            typer.echo(f"No metrics found for claim: {claim_id}", err=True)
            typer.echo(
                "Note: Metrics are only available for claims processed in the current session.",
                err=True,
            )
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
            typer.echo(
                f"    Latency: {summary.total_latency_ms:.0f}ms (avg: {summary.avg_latency_ms:.0f}ms)"
            )
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


def cmd_retention_enforce(
    dry_run: bool = False,
    years: int | None = None,
    include_litigation_hold: bool = False,
) -> None:
    """Archive claims older than retention period. Used by tests."""
    retention_enforce(dry_run, years, include_litigation_hold)


def cmd_document_retention_enforce(
    dry_run: bool = False,
    as_of: str | None = None,
) -> None:
    """Soft-archive documents past retention_date. Used by tests."""
    document_retention_enforce(dry_run, as_of)


def cmd_retention_purge(
    dry_run: bool = False,
    years: int | None = None,
    include_litigation_hold: bool = False,
) -> None:
    """Purge archived claims past purge horizon. Used by tests."""
    retention_purge(dry_run, years, include_litigation_hold)


if __name__ == "__main__":
    main()
