"""DPA (Data Processing Agreement) registry for subprocessor compliance tracking.

Tracks Data Processing Agreements with third-party subprocessors (LLM providers,
cloud storage, notification services, etc.) that process personal data on behalf
of the claims system operator.

Database table: ``dpa_registry``

Typical usage::

    from claim_agent.privacy.dpa_registry import (
        register_dpa,
        list_dpas,
        get_dpa,
        deactivate_dpa,
    )

    # Register a new DPA
    dpa_id = register_dpa(
        subprocessor_name="OpenAI",
        service_type="llm",
        data_categories=["claim_data", "incident_description"],
        purpose="Automated claims processing",
        destination_country="US",
        mechanism="scc",
        legal_basis="GDPR Art. 46(2)(c) SCCs (EC 2021/914 Module 2)",
        dpa_signed_date="2024-01-15",
        dpa_document_ref="contracts/openai-dpa-2024.pdf",
        supplementary_measures=["PII minimization", "TLS 1.2+"],
    )

    # List active DPAs
    dpas, total = list_dpas(active_only=True)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from claim_agent.db.database import get_connection, get_db_path, row_to_dict
from claim_agent.privacy.cross_border import classify_jurisdiction


def register_dpa(
    subprocessor_name: str,
    service_type: str,
    data_categories: list[str],
    purpose: str,
    destination_country: str,
    mechanism: str,
    *,
    legal_basis: str = "",
    dpa_signed_date: str | None = None,
    dpa_expiry_date: str | None = None,
    dpa_document_ref: str | None = None,
    supplementary_measures: list[str] | None = None,
    notes: str = "",
    actor_id: str = "system",
    db_path: str | None = None,
) -> int:
    """Register a new DPA entry in the subprocessor registry.

    Args:
        subprocessor_name: Name of the subprocessor (e.g. ``"OpenAI"``).
        service_type: Category of service: ``llm``, ``storage``, ``notification``,
            ``adapter``, or ``other``.
        data_categories: Personal data categories shared with the subprocessor
            (e.g. ``["claim_data", "vin", "incident_description"]``).
        purpose: Processing purpose description.
        destination_country: Country (or region) where the subprocessor processes data.
        mechanism: Transfer mechanism code: ``"scc"``, ``"adequacy_decision"``,
            ``"explicit_consent"``, ``"bcr"``, ``"legitimate_interests"``, or ``"none"``.
        legal_basis: Reference to the specific legal clause or agreement.
        dpa_signed_date: ISO date string when the DPA was signed (``"YYYY-MM-DD"``).
        dpa_expiry_date: ISO date string when the DPA expires.
        dpa_document_ref: Path or reference to the DPA document.
        supplementary_measures: List of technical/organisational measures applied.
        notes: Free-form compliance notes.
        actor_id: Who registered this entry (for audit).
        db_path: Optional DB path override.

    Returns:
        The ``id`` (integer primary key) of the newly created DPA row.
    """
    path = db_path or get_db_path()
    destination_zone = classify_jurisdiction(destination_country).value
    now = datetime.now(timezone.utc).isoformat()

    with get_connection(path) as conn:
        result = conn.execute(
            text("""
                INSERT INTO dpa_registry (
                    subprocessor_name, service_type, data_categories, purpose,
                    destination_country, destination_zone, mechanism, legal_basis,
                    dpa_signed_date, dpa_expiry_date, dpa_document_ref,
                    supplementary_measures, active, notes, created_by, created_at, updated_at
                ) VALUES (
                    :subprocessor_name, :service_type, :data_categories, :purpose,
                    :destination_country, :destination_zone, :mechanism, :legal_basis,
                    :dpa_signed_date, :dpa_expiry_date, :dpa_document_ref,
                    :supplementary_measures, 1, :notes, :created_by, :now, :now
                )
                RETURNING id
            """),
            {
                "subprocessor_name": subprocessor_name,
                "service_type": service_type,
                "data_categories": json.dumps(data_categories),
                "purpose": purpose,
                "destination_country": destination_country,
                "destination_zone": destination_zone,
                "mechanism": mechanism,
                "legal_basis": legal_basis,
                "dpa_signed_date": dpa_signed_date,
                "dpa_expiry_date": dpa_expiry_date,
                "dpa_document_ref": dpa_document_ref,
                "supplementary_measures": json.dumps(supplementary_measures or []),
                "notes": notes,
                "created_by": actor_id or None,
                "now": now,
            },
        )
        row = result.fetchone()
        return int(row[0]) if row else -1


def get_dpa(dpa_id: int, *, db_path: str | None = None) -> dict[str, Any] | None:
    """Retrieve a single DPA entry by ID.

    Returns:
        The DPA dict, or ``None`` if not found.
    """
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        row = conn.execute(
            text("SELECT * FROM dpa_registry WHERE id = :id"),
            {"id": dpa_id},
        ).fetchone()
        if row is None:
            return None
        return _deserialise_dpa(row_to_dict(row))


def list_dpas(
    *,
    active_only: bool = True,
    service_type: str | None = None,
    mechanism: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List DPA registry entries with optional filters.

    Args:
        active_only: When ``True`` (default), only return active DPAs.
        service_type: Filter by service category (e.g. ``"llm"``).
        mechanism: Filter by transfer mechanism code.
        limit: Maximum number of results.
        offset: Pagination offset.
        db_path: Optional DB path override.

    Returns:
        Tuple of ``(items, total_count)``.
    """
    path = db_path or get_db_path()
    where = "WHERE 1=1"
    params: dict[str, Any] = {}
    if active_only:
        where += " AND active = 1"
    if service_type:
        where += " AND service_type = :service_type"
        params["service_type"] = service_type
    if mechanism:
        where += " AND mechanism = :mechanism"
        params["mechanism"] = mechanism

    with get_connection(path) as conn:
        count_row = conn.execute(
            text(f"SELECT COUNT(*) FROM dpa_registry {where}"), params
        ).fetchone()
        total = count_row[0] if count_row and hasattr(count_row, "__getitem__") else 0

        params["limit"] = limit
        params["offset"] = offset
        rows = conn.execute(
            text(
                f"SELECT * FROM dpa_registry {where} "
                "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).fetchall()
        return [_deserialise_dpa(row_to_dict(r)) for r in rows], total


def deactivate_dpa(
    dpa_id: int,
    *,
    actor_id: str = "system",
    db_path: str | None = None,
) -> bool:
    """Mark a DPA entry as inactive (soft-delete).

    Args:
        dpa_id: ID of the DPA to deactivate.
        actor_id: Who deactivated this entry (for audit trail).
        db_path: Optional DB path override.

    Returns:
        ``True`` if a row was updated, ``False`` if the ID was not found.
    """
    path = db_path or get_db_path()
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(path) as conn:
        result = conn.execute(
            text(
                "UPDATE dpa_registry SET active = 0, updated_at = :now "
                "WHERE id = :id AND active = 1"
            ),
            {"id": dpa_id, "now": now},
        )
        return (result.rowcount or 0) > 0


def _deserialise_dpa(d: dict[str, Any]) -> dict[str, Any]:
    """Parse JSON list fields stored as TEXT in the DB."""
    for key in ("data_categories", "supplementary_measures"):
        val = d.get(key)
        if isinstance(val, str):
            try:
                d[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                d[key] = []
    return d
