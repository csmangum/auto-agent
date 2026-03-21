"""Tools for witness and attorney party intake (investigation / representation)."""

from __future__ import annotations

import json
import logging

from crewai.tools import tool

from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import DomainValidationError
from claim_agent.models.party import ClaimPartyInput, PartyRelationshipType
from claim_agent.utils.sanitization import sanitize_note

logger = logging.getLogger(__name__)


@tool("Record Witness Party")
def record_witness_party(
    claim_id: str,
    name: str,
    role: str = "",
    email: str = "",
    phone: str = "",
    address: str = "",
) -> str:
    """Add a witness party with optional contact and role (e.g. eyewitness, passenger).

    Use during investigation to capture who saw the loss and how to reach them.
    """
    claim_id = str(claim_id).strip()
    name = str(name).strip()
    role_val = str(role).strip() or None
    email_val = str(email).strip() or None
    phone_val = str(phone).strip() or None
    address_val = str(address).strip() or None
    if not claim_id:
        return json.dumps({"success": False, "error": "claim_id is required"})
    if not name:
        return json.dumps({"success": False, "error": "name is required"})
    try:
        repo = ClaimRepository()
        if repo.get_claim(claim_id) is None:
            return json.dumps({"success": False, "error": f"Claim not found: {claim_id}"})
        party = ClaimPartyInput(
            party_type="witness",
            name=name,
            email=email_val,
            phone=phone_val,
            address=address_val,
            role=role_val,
        )
        pid = repo.add_claim_party(claim_id, party)
        return json.dumps({"success": True, "party_id": pid, "party_type": "witness"})
    except Exception:
        logger.exception("record_witness_party failed claim_id=%s", claim_id)
        return json.dumps({"success": False, "error": "Unexpected error recording witness"})


@tool("Update Witness Party")
def update_witness_party(
    claim_id: str,
    party_id: int,
    name: str = "",
    role: str = "",
    email: str = "",
    phone: str = "",
    address: str = "",
) -> str:
    """Update an existing witness party (contact, role, name). Only non-empty fields apply."""
    claim_id = str(claim_id).strip()
    if not claim_id:
        return json.dumps({"success": False, "error": "claim_id is required"})
    try:
        repo = ClaimRepository()
        if repo.get_claim(claim_id) is None:
            return json.dumps({"success": False, "error": f"Claim not found: {claim_id}"})
        row = None
        for p in repo.get_claim_parties(claim_id, party_type="witness"):
            if int(p["id"]) == int(party_id):
                row = p
                break
        if row is None:
            return json.dumps(
                {"success": False, "error": f"No witness party_id={party_id} on claim {claim_id}"}
            )
        updates: dict = {}
        if str(name).strip():
            updates["name"] = str(name).strip()
        if str(role).strip():
            updates["role"] = str(role).strip()
        if str(email).strip():
            updates["email"] = str(email).strip()
        if str(phone).strip():
            updates["phone"] = str(phone).strip()
        if str(address).strip():
            updates["address"] = str(address).strip()
        if not updates:
            return json.dumps({"success": False, "error": "No fields to update"})
        repo.update_claim_party(int(party_id), updates)
        return json.dumps({"success": True, "party_id": int(party_id)})
    except Exception:
        logger.exception("update_witness_party failed claim_id=%s party_id=%s", claim_id, party_id)
        return json.dumps({"success": False, "error": "Unexpected error updating witness"})


@tool("Record Witness Statement")
def record_witness_statement(
    claim_id: str,
    witness_party_id: int,
    statement_text: str,
    *,
    actor_id: str = "party_intake_agent",
) -> str:
    """Persist a witness statement as a claim note, attributed to the witness party id."""
    claim_id = str(claim_id).strip()
    body = sanitize_note(statement_text) or ""
    if not claim_id:
        return json.dumps({"success": False, "error": "claim_id is required"})
    if not body.strip():
        return json.dumps({"success": False, "error": "statement_text is required"})
    try:
        repo = ClaimRepository()
        if repo.get_claim(claim_id) is None:
            return json.dumps({"success": False, "error": f"Claim not found: {claim_id}"})
        wid = int(witness_party_id)
        ok = False
        for p in repo.get_claim_parties(claim_id, party_type="witness"):
            if int(p["id"]) == wid:
                ok = True
                break
        if not ok:
            return json.dumps(
                {"success": False, "error": f"party_id {wid} is not a witness on claim {claim_id}"}
            )
        note = f"[witness_statement party_id={wid}]\n{body.strip()}"
        repo.add_note(claim_id, note, actor_id=str(actor_id).strip() or "party_intake_agent")
        return json.dumps({"success": True, "witness_party_id": wid})
    except Exception:
        logger.exception(
            "record_witness_statement failed claim_id=%s witness_party_id=%s",
            claim_id,
            witness_party_id,
        )
        return json.dumps({"success": False, "error": "Unexpected error recording statement"})


@tool("Record Attorney Representation")
def record_attorney_representation(
    claim_id: str,
    attorney_name: str,
    email: str = "",
    phone: str = "",
    *,
    claimant_party_id: int | None = None,
) -> str:
    """Add an attorney party and link claimant -> attorney (represented_by).

    After this, send_user_message with user_type=claimant routes to the attorney when
    the attorney has email or phone (same as manual represented_by edge).
    Optionally pass claimant_party_id when multiple claimants exist.
    """
    claim_id = str(claim_id).strip()
    attorney_name = str(attorney_name).strip()
    email_val = str(email).strip() or None
    phone_val = str(phone).strip() or None
    if not claim_id:
        return json.dumps({"success": False, "error": "claim_id is required"})
    if not attorney_name:
        return json.dumps({"success": False, "error": "attorney_name is required"})
    try:
        repo = ClaimRepository()
        if repo.get_claim(claim_id) is None:
            return json.dumps({"success": False, "error": f"Claim not found: {claim_id}"})

        if claimant_party_id is not None:
            cid = int(claimant_party_id)
            parties = repo.get_claim_parties(claim_id, party_type="claimant")
            match = next((p for p in parties if int(p["id"]) == cid), None)
            if match is None:
                return json.dumps(
                    {"success": False, "error": f"claimant_party_id {cid} not on claim {claim_id}"}
                )
            claimant_id = cid
            claimant_row = match
        else:
            claimant = repo.get_claim_party_by_type(claim_id, "claimant")
            if claimant is None:
                return json.dumps(
                    {
                        "success": False,
                        "error": "No claimant party on claim; add claimant first or pass claimant_party_id",
                    }
                )
            claimant_id = int(claimant["id"])
            claimant_row = claimant

        if claimant_row:
            for r in claimant_row.get("relationships") or []:
                if r.get("relationship_type") == PartyRelationshipType.REPRESENTED_BY.value:
                    return json.dumps(
                        {
                            "success": True,
                            "message": "Claimant already has represented_by relationship; no change",
                            "claimant_party_id": claimant_id,
                        }
                    )

        attorney_party = ClaimPartyInput(
            party_type="attorney",
            name=attorney_name,
            email=email_val,
            phone=phone_val,
            role="counsel",
        )
        attorney_id = repo.add_claim_party(claim_id, attorney_party)
        repo.add_claim_party_relationship(
            claim_id,
            claimant_id,
            attorney_id,
            PartyRelationshipType.REPRESENTED_BY.value,
        )
        return json.dumps(
            {
                "success": True,
                "attorney_party_id": attorney_id,
                "claimant_party_id": claimant_id,
            }
        )
    except DomainValidationError as e:
        return json.dumps({"success": False, "error": str(e)})
    except Exception:
        logger.exception("record_attorney_representation failed claim_id=%s", claim_id)
        return json.dumps({"success": False, "error": "Unexpected error recording attorney"})
