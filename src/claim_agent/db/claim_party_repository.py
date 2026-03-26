"""Claim party repository: CRUD for claim_parties and claim_party_relationships tables."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from claim_agent.db.database import get_connection, row_to_dict
from claim_agent.exceptions import DomainValidationError
from claim_agent.models.party import ClaimPartyInput, PartyRelationshipType


class ClaimPartyRepository:
    """Repository for claim party and party relationship persistence."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

    def add_claim_party_core(self, conn: Any, claim_id: str, party: ClaimPartyInput) -> int:
        """Insert a claim party using an existing connection. Does not commit."""
        result = conn.execute(
            text("""
            INSERT INTO claim_parties (
                claim_id, party_type, name, email, phone, address, role,
                consent_status, authorization_status
            ) VALUES (:claim_id, :party_type, :name, :email, :phone, :address, :role,
                     :consent_status, :authorization_status)
            RETURNING id
            """),
            {
                "claim_id": claim_id,
                "party_type": party.party_type,
                "name": party.name,
                "email": party.email,
                "phone": party.phone,
                "address": party.address,
                "role": party.role,
                "consent_status": party.consent_status or "pending",
                "authorization_status": party.authorization_status or "pending",
            },
        )
        rid = result.fetchone()
        return int(rid[0]) if rid else 0

    def add_claim_party(self, claim_id: str, party: ClaimPartyInput) -> int:
        """Insert a claim party. Returns party id."""
        with get_connection(self._db_path) as conn:
            return self.add_claim_party_core(conn, claim_id, party)

    def add_claim_party_relationship(
        self,
        claim_id: str,
        from_party_id: int,
        to_party_id: int,
        relationship_type: str,
    ) -> int:
        """Insert a party-to-party edge. Validates both parties belong to claim_id.

        Returns new relationship row id.
        """
        # Extract .value if it's an enum, otherwise treat as string
        rt_value = getattr(relationship_type, "value", relationship_type)
        rt = str(rt_value).strip().lower()
        allowed = {e.value for e in PartyRelationshipType}
        if rt not in allowed:
            raise DomainValidationError(
                f"Invalid relationship_type {relationship_type!r}; expected one of {sorted(allowed)}"
            )
        if from_party_id == to_party_id:
            raise DomainValidationError("from_party_id and to_party_id must differ")

        with get_connection(self._db_path) as conn:
            fr = conn.execute(
                text("SELECT id, claim_id FROM claim_parties WHERE id = :id"),
                {"id": from_party_id},
            ).fetchone()
            to = conn.execute(
                text("SELECT id, claim_id FROM claim_parties WHERE id = :id"),
                {"id": to_party_id},
            ).fetchone()
            if fr is None or to is None:
                raise DomainValidationError("One or both party IDs do not exist")
            fr_d, to_d = row_to_dict(fr), row_to_dict(to)
            if fr_d.get("claim_id") != claim_id or to_d.get("claim_id") != claim_id:
                raise DomainValidationError("Parties must belong to the same claim")

            try:
                result = conn.execute(
                    text("""
                    INSERT INTO claim_party_relationships (
                        from_party_id, to_party_id, relationship_type
                    ) VALUES (:from_id, :to_id, :rtype)
                    RETURNING id
                    """),
                    {"from_id": from_party_id, "to_id": to_party_id, "rtype": rt},
                )
            except IntegrityError as e:
                raise DomainValidationError(
                    "Duplicate party relationship for this from_party_id, to_party_id, "
                    "and relationship_type"
                ) from e
            row = result.fetchone()
            return int(row[0]) if row else 0

    def delete_claim_party_relationship(self, claim_id: str, relationship_id: int) -> bool:
        """Delete a party edge if it exists and both endpoints belong to claim_id."""
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text("""
                DELETE FROM claim_party_relationships
                WHERE id = :rid
                  AND from_party_id IN (SELECT id FROM claim_parties WHERE claim_id = :cid)
                  AND to_party_id IN (SELECT id FROM claim_parties WHERE claim_id = :cid)
                """),
                {"rid": relationship_id, "cid": claim_id},
            )
            return bool(result.rowcount and result.rowcount > 0)

    def get_claim_parties(
        self, claim_id: str, party_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch parties for a claim, optionally filtered by party_type.

        Each party dict includes ``relationships``: outgoing edges from claim_party_relationships
        (ordered by relationship id ascending; first ``represented_by`` wins for contact routing).
        """
        with get_connection(self._db_path) as conn:
            if party_type:
                rows = conn.execute(
                    text(
                        "SELECT * FROM claim_parties WHERE claim_id = :claim_id AND party_type = :party_type"
                    ),
                    {"claim_id": claim_id, "party_type": party_type},
                ).fetchall()
            else:
                rows = conn.execute(
                    text("SELECT * FROM claim_parties WHERE claim_id = :claim_id"),
                    {"claim_id": claim_id},
                ).fetchall()
            parties = [row_to_dict(r) for r in rows]
            # Strip legacy column that older SQLite schemas may still expose.
            for p in parties:
                p.pop("represented_by_id", None)
            if not parties:
                return []
            party_ids = [int(p["id"]) for p in parties]
            placeholders = ", ".join(f":pid{i}" for i in range(len(party_ids)))
            params: dict[str, Any] = {f"pid{i}": pid for i, pid in enumerate(party_ids)}
            rel_rows = conn.execute(
                text(
                    f"SELECT * FROM claim_party_relationships WHERE from_party_id IN ({placeholders}) "
                    "ORDER BY id ASC"
                ),
                params,
            ).fetchall()
        by_from: dict[int, list[dict[str, Any]]] = {}
        for r in rel_rows:
            d = row_to_dict(r)
            fid = int(d["from_party_id"])
            by_from.setdefault(fid, []).append(
                {
                    "id": d["id"],
                    "to_party_id": d["to_party_id"],
                    "relationship_type": d["relationship_type"],
                    "created_at": d.get("created_at"),
                }
            )
        for p in parties:
            p["relationships"] = by_from.get(int(p["id"]), [])
        return parties

    def get_claim_party_by_type(self, claim_id: str, party_type: str) -> dict[str, Any] | None:
        """Get first party of given type for a claim."""
        parties = self.get_claim_parties(claim_id, party_type=party_type)
        return parties[0] if parties else None

    def update_claim_party(self, party_id: int, updates: dict[str, Any]) -> None:
        """Update a claim party by id. Only provided keys are updated."""
        allowed = {
            "name",
            "email",
            "phone",
            "address",
            "role",
            "consent_status",
            "authorization_status",
        }
        to_set = {k: v for k, v in updates.items() if k in allowed and v is not None}
        if not to_set:
            return
        now = datetime.now(timezone.utc).isoformat()
        set_parts = [f"{k} = :{k}" for k in to_set] + ["updated_at = :now"]
        set_clause = ", ".join(set_parts)
        params: dict[str, Any] = dict(to_set)
        params["now"] = now
        params["id"] = party_id
        with get_connection(self._db_path) as conn:
            conn.execute(text(f"UPDATE claim_parties SET {set_clause} WHERE id = :id"), params)

    def get_primary_contact_for_user_type(
        self, claim_id: str, user_type: str
    ) -> dict[str, Any] | None:
        """Resolve contact for user_type. If claimant has attorney, return attorney.

        Maps: claimant->claimant or attorney; policyholder->policyholder.
        repair_shop/siu/adjuster/other: no party record, return None.
        """
        user_type = str(user_type).strip().lower()
        if user_type == "claimant":
            claimant = self.get_claim_party_by_type(claim_id, "claimant")
            if claimant:
                cid = int(claimant["id"])
                with get_connection(self._db_path) as conn:
                    row = conn.execute(
                        text("""
                        SELECT cp.* FROM claim_party_relationships r
                        JOIN claim_parties cp ON cp.id = r.to_party_id
                        WHERE r.from_party_id = :from_id
                          AND r.relationship_type = :rtype
                          AND cp.claim_id = :claim_id
                        ORDER BY r.id ASC
                        LIMIT 1
                        """),
                        {
                            "from_id": cid,
                            "rtype": PartyRelationshipType.REPRESENTED_BY.value,
                            "claim_id": claim_id,
                        },
                    ).fetchone()
                if row:
                    attorney = row_to_dict(row)
                    if attorney.get("email") or attorney.get("phone"):
                        return attorney
            return (
                claimant
                if (claimant and (claimant.get("email") or claimant.get("phone")))
                else None
            )
        if user_type == "policyholder":
            ph = self.get_claim_party_by_type(claim_id, "policyholder")
            return ph if (ph and (ph.get("email") or ph.get("phone"))) else None
        if user_type == "attorney":
            for row in self.get_claim_parties(claim_id, party_type="attorney"):
                if row.get("email") or row.get("phone"):
                    return row
            return None
        if user_type == "witness":
            for row in self.get_claim_parties(claim_id, party_type="witness"):
                if row.get("email") or row.get("phone"):
                    return row
            return None
        return None
