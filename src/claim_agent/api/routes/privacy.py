"""Privacy compliance API routes: cross-border transfer controls and DPA registry.

Endpoints
---------

GET  /api/privacy/cross-border/data-flows
    Return the catalog of known data flows that may cross jurisdictional borders.

GET  /api/privacy/cross-border/transfer-log
    Return the audit log of cross-border transfer events.

GET  /api/privacy/cross-border/dpa-registry
    List registered Data Processing Agreements with subprocessors.

POST /api/privacy/cross-border/dpa-registry
    Register a new DPA entry.

DELETE /api/privacy/cross-border/dpa-registry/{dpa_id}
    Deactivate (soft-delete) a DPA entry.

GET  /api/privacy/cross-border/check
    Evaluate whether a proposed transfer is permitted under the active policy.

All write endpoints require the ``admin`` role.
Read endpoints also require auth when auth is configured.
"""

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import require_role
from claim_agent.privacy.cross_border import (
    TransferMechanism,
    check_transfer_permitted,
    classify_jurisdiction,
    get_known_data_flows,
    list_transfer_log,
)
from claim_agent.privacy.dpa_registry import (
    deactivate_dpa,
    get_dpa,
    list_dpas,
    register_dpa,
)

router = APIRouter(prefix="/privacy", tags=["privacy"])


# ---------------------------------------------------------------------------
# Data flows catalog
# ---------------------------------------------------------------------------


@router.get("/cross-border/data-flows")
def get_data_flows(
    cross_border_only: bool = Query(
        False,
        description="When true, only return flows that cross jurisdiction zones",
    ),
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Return the catalog of data flows that may involve cross-border transfers.

    Each entry documents a category of data movement in the claims system,
    together with its transfer mechanism, legal basis, and supplementary measures.
    """
    flows = get_known_data_flows(cross_border_only=cross_border_only)
    return {
        "data_flows": flows,
        "total": len(flows),
        "cross_border_only": cross_border_only,
    }


# ---------------------------------------------------------------------------
# Transfer log
# ---------------------------------------------------------------------------


@router.get("/cross-border/transfer-log")
def get_transfer_log(
    claim_id: str | None = Query(None, description="Filter by claim ID"),
    flow_name: str | None = Query(None, description="Filter by data flow name"),
    policy_decision: str | None = Query(
        None, description="Filter by policy decision (allow|audit|block)"
    ),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Return the cross-border transfer audit log.

    Each entry records a data transfer event that was evaluated by the
    cross-border transfer check, including the policy decision and mechanism.
    """
    items, total = list_transfer_log(
        claim_id=claim_id,
        flow_name=flow_name,
        policy_decision=policy_decision,
        limit=limit,
        offset=offset,
    )
    return {"transfers": items, "total": total, "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# Transfer check (dry-run)
# ---------------------------------------------------------------------------


@router.get("/cross-border/check")
def check_transfer(
    source_jurisdiction: str = Query(
        ..., description="Source jurisdiction (country or US state)"
    ),
    destination_provider: str = Query(..., description="Destination provider name"),
    data_categories: str = Query(
        "claim_data",
        description="Comma-separated list of personal data categories",
    ),
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Evaluate whether a proposed cross-border transfer is permitted.

    Applies the configured ``CROSS_BORDER_POLICY`` and returns the
    transfer mechanism, policy decision, and any compliance warnings.
    This is a read-only dry-run; no transfer is performed or logged.
    """
    categories = [c.strip() for c in data_categories.split(",") if c.strip()]
    result = check_transfer_permitted(
        source_jurisdiction=source_jurisdiction,
        destination_provider=destination_provider,
        data_categories=categories,
    )
    result["source_jurisdiction"] = source_jurisdiction
    result["destination_provider"] = destination_provider
    result["data_categories"] = categories
    return result


# ---------------------------------------------------------------------------
# DPA registry
# ---------------------------------------------------------------------------


class DPARegistryInput(BaseModel):
    """Request body for POST /privacy/cross-border/dpa-registry."""

    subprocessor_name: str = Field(..., description="Name of the subprocessor")
    service_type: str = Field(
        ...,
        description="Service category: llm, storage, notification, adapter, or other",
    )
    data_categories: list[str] = Field(
        ..., description="Personal data categories shared with the subprocessor"
    )
    purpose: str = Field(..., description="Processing purpose")
    destination_country: str = Field(
        ..., description="Country where the subprocessor processes data"
    )
    mechanism: str = Field(
        ...,
        description=(
            "Transfer mechanism: scc, adequacy_decision, explicit_consent, "
            "bcr, legitimate_interests, or none"
        ),
    )
    legal_basis: str = Field(default="", description="Reference to legal clause or agreement")
    dpa_signed_date: str | None = Field(
        None, description="ISO date the DPA was signed (YYYY-MM-DD)"
    )
    dpa_expiry_date: str | None = Field(
        None, description="ISO date the DPA expires (YYYY-MM-DD)"
    )
    dpa_document_ref: str | None = Field(
        None, description="Path or reference to the DPA document"
    )
    supplementary_measures: list[str] = Field(
        default_factory=list,
        description="Technical/organisational supplementary measures",
    )
    notes: str = Field(default="", description="Free-form compliance notes")


@router.post("/cross-border/dpa-registry", status_code=201)
def create_dpa(
    body: DPARegistryInput = Body(...),
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Register a new DPA with a subprocessor in the compliance registry.

    Provide the subprocessor name, service type, data categories, processing
    purpose, destination country, and transfer mechanism.  The destination
    jurisdiction zone is derived automatically from ``destination_country``.
    """
    # Validate mechanism
    try:
        TransferMechanism(body.mechanism)
    except ValueError:
        valid = [m.value for m in TransferMechanism]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mechanism '{body.mechanism}'. Valid values: {valid}",
        )

    dpa_id = register_dpa(
        subprocessor_name=body.subprocessor_name,
        service_type=body.service_type,
        data_categories=body.data_categories,
        purpose=body.purpose,
        destination_country=body.destination_country,
        mechanism=body.mechanism,
        legal_basis=body.legal_basis,
        dpa_signed_date=body.dpa_signed_date,
        dpa_expiry_date=body.dpa_expiry_date,
        dpa_document_ref=body.dpa_document_ref,
        supplementary_measures=body.supplementary_measures,
        notes=body.notes,
        actor_id=_auth.identity or "api",
    )

    dpa = get_dpa(dpa_id)
    return {
        "id": dpa_id,
        "destination_zone": classify_jurisdiction(body.destination_country).value,
        **(dpa or {}),
    }


@router.get("/cross-border/dpa-registry")
def list_dpa_registry(
    active_only: bool = Query(True, description="When true, only return active DPAs"),
    service_type: str | None = Query(None, description="Filter by service type"),
    mechanism: str | None = Query(None, description="Filter by transfer mechanism"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """List registered Data Processing Agreements with subprocessors.

    Returns DPA entries filterable by active status, service type, and mechanism.
    """
    items, total = list_dpas(
        active_only=active_only,
        service_type=service_type,
        mechanism=mechanism,
        limit=limit,
        offset=offset,
    )
    return {"dpas": items, "total": total, "limit": limit, "offset": offset}


@router.get("/cross-border/dpa-registry/{dpa_id}")
def get_dpa_entry(
    dpa_id: int,
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Retrieve a single DPA entry by ID."""
    dpa = get_dpa(dpa_id)
    if dpa is None:
        raise HTTPException(status_code=404, detail=f"DPA entry {dpa_id} not found")
    return dpa


@router.delete("/cross-border/dpa-registry/{dpa_id}")
def delete_dpa_entry(
    dpa_id: int,
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Deactivate (soft-delete) a DPA registry entry.

    The entry is marked inactive and retained for audit purposes.
    """
    updated = deactivate_dpa(dpa_id, actor_id=_auth.identity or "api")
    if not updated:
        raise HTTPException(
            status_code=404,
            detail=f"DPA entry {dpa_id} not found or already inactive",
        )
    return {"id": dpa_id, "active": False, "message": "DPA entry deactivated"}
