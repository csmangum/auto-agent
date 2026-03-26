"""Claim search and relationship graph repository.

Contains methods for searching claims by VIN/policy/date, finding related claims by
party address or provider name, and building the fraud-detection relationship graph
snapshot via BFS traversal.
"""

import logging
from typing import Any

from sqlalchemy import text

from claim_agent.db.database import get_connection, is_postgres_backend, row_to_dict
from claim_agent.utils.graph_contact_normalize import (
    normalize_party_email_for_graph,
    normalize_party_phone_for_graph,
    sql_expr_phone_normalized_postgres,
)

# Relation types for build_relationship_snapshot edges
RELATION_SHARED_VIN = "shared_vin"
RELATION_SHARED_ADDRESS = "shared_address"
RELATION_SHARED_PROVIDER = "shared_provider"
RELATION_SHARED_PHONE = "shared_phone"
RELATION_SHARED_EMAIL = "shared_email"

_HIGH_RISK_RELATIONS = frozenset(
    {RELATION_SHARED_PROVIDER, RELATION_SHARED_ADDRESS, RELATION_SHARED_PHONE, RELATION_SHARED_EMAIL}
)


def resolve_edge_relations(
    src_vins: list[str],
    src_addresses: list[str],
    src_provider_names: list[str],
    src_phones: list[str],
    src_emails: list[str],
    target_claim: dict[str, Any],
    target_parties: list[dict[str, Any]],
) -> list[str]:
    """Return RELATION_SHARED_* constants that connect source link keys to the target claim.

    Checks VIN, party address, provider name, phone, and email. Each relation type is
    included at most once. Insertion order is preserved.

    Returns a list of ``RELATION_SHARED_*`` constants (insertion order) that apply.
    Empty list means no link was detected.
    """
    rtypes: list[str] = []

    t_vin = str(target_claim.get("vin") or "").strip()
    if t_vin and t_vin in src_vins:
        rtypes.append(RELATION_SHARED_VIN)

    t_addresses = {
        str(p.get("address")).strip().lower()
        for p in target_parties
        if isinstance(p.get("address"), str) and str(p.get("address")).strip()
    }
    if src_addresses and t_addresses & set(src_addresses):
        rtypes.append(RELATION_SHARED_ADDRESS)

    t_providers = {
        str(p.get("name")).strip().lower()
        for p in target_parties
        if str(p.get("party_type") or "").strip() == "provider"
        and isinstance(p.get("name"), str)
        and str(p.get("name")).strip()
    }
    if src_provider_names and t_providers & set(src_provider_names):
        rtypes.append(RELATION_SHARED_PROVIDER)

    t_phones = {
        n
        for p in target_parties
        if (n := normalize_party_phone_for_graph(p.get("phone"))) is not None
    }
    if src_phones and t_phones & set(src_phones):
        rtypes.append(RELATION_SHARED_PHONE)

    t_emails = {
        n
        for p in target_parties
        if (n := normalize_party_email_for_graph(p.get("email"))) is not None
    }
    if src_emails and t_emails & set(src_emails):
        rtypes.append(RELATION_SHARED_EMAIL)

    return rtypes


class ClaimSearchRepository:
    """Repository for claim search and fraud-detection relationship graph queries."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_claim(self, claim_id: str) -> dict[str, Any] | None:
        """Fetch a single claim row by ID."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
        return row_to_dict(row) if row else None

    def _get_claim_parties(self, claim_id: str) -> list[dict[str, Any]]:
        """Fetch parties for a claim."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("SELECT * FROM claim_parties WHERE claim_id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def _extract_graph_link_keys(
        self,
        claim: dict[str, Any],
        parties: list[dict[str, Any]],
    ) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
        """Extract (vins, addresses, provider_names, phones, emails) link keys from a claim.

        Returns five lists suitable for passing directly to ``_query_related_ids_on_conn``.
        Each list is de-duplicated and normalized.
        """
        vin = str(claim.get("vin") or "").strip()
        vins = [vin] if vin else []
        addresses = list(
            dict.fromkeys(
                str(p.get("address")).strip().lower()
                for p in parties
                if isinstance(p.get("address"), str) and str(p.get("address")).strip()
            )
        )
        provider_names = list(
            dict.fromkeys(
                str(p.get("name")).strip().lower()
                for p in parties
                if str(p.get("party_type") or "").strip() == "provider"
                and isinstance(p.get("name"), str)
                and str(p.get("name")).strip()
            )
        )
        phones = list(
            dict.fromkeys(
                n
                for p in parties
                if (n := normalize_party_phone_for_graph(p.get("phone"))) is not None
            )
        )
        emails = list(
            dict.fromkeys(
                n
                for p in parties
                if (n := normalize_party_email_for_graph(p.get("email"))) is not None
            )
        )
        return vins, addresses, provider_names, phones, emails

    def _query_related_ids_on_conn(
        self,
        conn: Any,
        *,
        vins: list[str],
        addresses: list[str],
        provider_names: list[str],
        phones_unique: list[str],
        emails_unique: list[str],
        exclude_ids: set[str],
        limit: int,
    ) -> set[str]:
        """Batch-query claim IDs related by any shared link key on the given connection.

        All sub-queries run on ``conn`` to avoid opening extra connections (no N+1
        connection storms). Returned IDs exclude any ID present in ``exclude_ids``.
        Each sub-query is individually bounded by ``limit``.
        """
        related: set[str] = set()

        if vins:
            v_params: dict[str, Any] = {"limit": limit}
            for i, v in enumerate(vins):
                v_params[f"v{i}"] = v
            v_in = ", ".join(f":v{i}" for i in range(len(vins)))
            rows = conn.execute(
                text(
                    f"SELECT DISTINCT id FROM claims WHERE vin IN ({v_in}) ORDER BY id LIMIT :limit"
                ),
                v_params,
            ).fetchall()
            for r in rows:
                rid = str(r[0] if r else "").strip()
                if rid and rid not in exclude_ids:
                    related.add(rid)

        if addresses:
            params: dict[str, Any] = {"limit": limit}
            for i, addr in enumerate(addresses):
                params[f"addr{i}"] = addr
            placeholders = ", ".join(f":addr{i}" for i in range(len(addresses)))
            rows = conn.execute(
                text(f"""
                SELECT DISTINCT c.id
                FROM claim_parties cp
                JOIN claims c ON c.id = cp.claim_id
                WHERE lower(trim(cp.address)) IN ({placeholders})
                ORDER BY c.id
                LIMIT :limit
                """),
                params,
            ).fetchall()
            for r in rows:
                rid = str(r[0] if r else "").strip()
                if rid and rid not in exclude_ids:
                    related.add(rid)

        if provider_names:
            params = {"limit": limit}
            for i, pn in enumerate(provider_names):
                params[f"pn{i}"] = pn
            placeholders = ", ".join(f":pn{i}" for i in range(len(provider_names)))
            rows = conn.execute(
                text(f"""
                SELECT DISTINCT c.id
                FROM claim_parties cp
                JOIN claims c ON c.id = cp.claim_id
                WHERE cp.party_type = 'provider'
                  AND lower(trim(cp.name)) IN ({placeholders})
                ORDER BY c.id
                LIMIT :limit
                """),
                params,
            ).fetchall()
            for r in rows:
                rid = str(r[0] if r else "").strip()
                if rid and rid not in exclude_ids:
                    related.add(rid)

        if emails_unique:
            params = {"limit": limit}
            for i, em in enumerate(emails_unique):
                params[f"em{i}"] = em
            placeholders = ", ".join(f":em{i}" for i in range(len(emails_unique)))
            rows = conn.execute(
                text(f"""
                SELECT DISTINCT c.id
                FROM claim_parties cp
                JOIN claims c ON c.id = cp.claim_id
                WHERE lower(trim(cp.email)) IN ({placeholders})
                ORDER BY c.id
                LIMIT :limit
                """),
                params,
            ).fetchall()
            for r in rows:
                rid = str(r[0] if r else "").strip()
                if rid and rid not in exclude_ids:
                    related.add(rid)

        if phones_unique:
            phone_expr = (
                sql_expr_phone_normalized_postgres()
                if is_postgres_backend()
                else "graph_phone_digits(cp.phone)"
            )
            params = {"limit": limit}
            for i, ph in enumerate(phones_unique):
                params[f"ph{i}"] = ph
            placeholders = ", ".join(f":ph{i}" for i in range(len(phones_unique)))
            rows = conn.execute(
                text(f"""
                SELECT DISTINCT c.id
                FROM claim_parties cp
                JOIN claims c ON c.id = cp.claim_id
                WHERE {phone_expr} IN ({placeholders})
                ORDER BY c.id
                LIMIT :limit
                """),
                params,
            ).fetchall()
            for r in rows:
                rid = str(r[0] if r else "").strip()
                if rid and rid not in exclude_ids:
                    related.add(rid)

        return related

    # ------------------------------------------------------------------
    # Public search methods
    # ------------------------------------------------------------------

    def search_claims(
        self,
        vin: str | None = None,
        incident_date: str | None = None,
        policy_number: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search claims by VIN, policy_number and/or incident_date.

        All parameters optional; if all None, returns [].
        """
        vin = None if vin is None else str(vin).strip()
        incident_date = None if incident_date is None else str(incident_date).strip()
        policy_number = None if policy_number is None else str(policy_number).strip()
        if not vin and not incident_date and not policy_number:
            return []
        with get_connection(self._db_path) as conn:
            conditions = []
            params: dict[str, Any] = {}
            if vin:
                conditions.append("vin = :vin")
                params["vin"] = vin
            if incident_date:
                conditions.append("incident_date = :incident_date")
                params["incident_date"] = incident_date
            if policy_number:
                conditions.append("policy_number = :policy_number")
                params["policy_number"] = policy_number
            where_clause = " AND ".join(conditions)
            rows = conn.execute(
                text(f"SELECT * FROM claims WHERE {where_clause}"),
                params,
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_claims_by_party_address(
        self,
        address: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return claims linked to parties at a matching address."""
        addr = str(address).strip()
        if not addr:
            return []
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT DISTINCT c.*
                FROM claim_parties cp
                JOIN claims c ON c.id = cp.claim_id
                WHERE lower(trim(cp.address)) = lower(trim(:addr))
                ORDER BY c.created_at DESC
                LIMIT :limit
                """),
                {"addr": addr, "limit": limit},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_claims_by_provider_name(
        self,
        provider_name: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return claims linked to provider parties with matching name."""
        name = str(provider_name).strip()
        if not name:
            return []
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT DISTINCT c.*
                FROM claim_parties cp
                JOIN claims c ON c.id = cp.claim_id
                WHERE cp.party_type = 'provider'
                  AND lower(trim(cp.name)) = lower(trim(:name))
                ORDER BY c.created_at DESC
                LIMIT :limit
                """),
                {"name": name, "limit": limit},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def build_relationship_snapshot(
        self,
        *,
        claim_id: str,
        max_nodes: int = 100,
        max_depth: int = 1,
    ) -> dict[str, Any]:
        """Build an in-memory bounded relationship graph snapshot from existing claims/parties.

        Performs BFS traversal up to depth 2. At each depth, related claims are found
        by shared VIN, party address, provider name, normalized phone, or normalized
        email. A strict node budget (``max_nodes``) limits the total related nodes;
        when the budget would be exceeded, nodes are selected deterministically by
        ascending claim ID (BFS-level order).

        All DB lookups use batch IN-clause queries on a single connection to avoid
        N+1 connection churn.

        This is a migration-ready compatibility layer. It derives graph signals from
        existing tables without requiring dedicated graph persistence.

        Args:
            claim_id: Root claim ID.
            max_nodes: Budget for *related* claim nodes (does not include the root node
                itself, so ``node_count`` in the result can be at most ``max_nodes + 1``).
                The budget is shared across all hops; when the budget would be exceeded,
                nodes are selected deterministically by ascending claim ID.
            max_depth: Graph traversal depth. 1 returns direct (1-hop) neighbors only.
                2 also expands from each 1-hop neighbor. Values > 2 are capped to 2.
        """
        logger = logging.getLogger(__name__)
        effective_depth = min(max(max_depth, 1), 2)
        if max_depth > 2:
            logger.debug(
                "build_relationship_snapshot max_depth=%s > 2; capping to 2",
                max_depth,
            )
        elif max_depth == 2:
            logger.debug("build_relationship_snapshot max_depth=2; performing 2-hop BFS")

        root_claim = self._get_claim(claim_id)
        if root_claim is None:
            return {
                "claim_id": claim_id,
                "max_nodes": max_nodes,
                "node_count": 0,
                "edge_count": 0,
                "high_risk_link_count": 0,
                "dense_cluster_detected": False,
                "signals": [],
                "nodes": [],
                "edges": [],
            }

        root_parties = self._get_claim_parties(claim_id)
        root_vins, root_addresses, root_providers, root_phones, root_emails = (
            self._extract_graph_link_keys(root_claim, root_parties)
        )

        hop1_ids: set[str] = set()
        hop2_ids: set[str] = set()
        hop1_claims_by_id: dict[str, dict[str, Any]] = {}
        hop1_parties_by_id: dict[str, list[dict[str, Any]]] = {}
        hop2_claims_by_id: dict[str, dict[str, Any]] = {}
        hop2_parties_by_id: dict[str, list[dict[str, Any]]] = {}

        with get_connection(self._db_path) as conn:
            # ── Hop 1: find claims directly related to the root ────────────────
            hop1_ids = self._query_related_ids_on_conn(
                conn,
                vins=root_vins,
                addresses=root_addresses,
                provider_names=root_providers,
                phones_unique=root_phones,
                emails_unique=root_emails,
                exclude_ids={claim_id},
                # Over-fetch (×5) to account for duplicates across link-key types before
                # the final deduplication and budget trim below.
                limit=max_nodes * 5,
            )
            if len(hop1_ids) > max_nodes:
                hop1_ids = set(sorted(hop1_ids)[:max_nodes])

            if hop1_ids:
                sorted_hop1 = sorted(hop1_ids)
                h1_params: dict[str, Any] = {
                    f"id{i}": hid for i, hid in enumerate(sorted_hop1)
                }
                h1_in = ", ".join(f":id{i}" for i in range(len(sorted_hop1)))
                for row in conn.execute(
                    text(f"SELECT * FROM claims WHERE id IN ({h1_in})"), h1_params
                ).fetchall():
                    d = row_to_dict(row)
                    hop1_claims_by_id[d["id"]] = d
                for row in conn.execute(
                    text(f"SELECT * FROM claim_parties WHERE claim_id IN ({h1_in})"),
                    h1_params,
                ).fetchall():
                    p = row_to_dict(row)
                    hop1_parties_by_id.setdefault(p["claim_id"], []).append(p)

                # ── Hop 2: expand from each 1-hop neighbor ─────────────────────
                if effective_depth >= 2:
                    remaining = max_nodes - len(hop1_ids)
                    if remaining > 0:
                        # Aggregate link keys from all hop1 nodes for bulk queries.
                        agg_vins: list[str] = []
                        agg_addresses: list[str] = []
                        agg_providers: list[str] = []
                        agg_phones: list[str] = []
                        agg_emails: list[str] = []
                        seen_v: set[str] = set()
                        seen_a: set[str] = set()
                        seen_p: set[str] = set()
                        seen_ph: set[str] = set()
                        seen_em: set[str] = set()
                        for hid in sorted_hop1:
                            h_vins, h_addrs, h_provs, h_phones, h_emails = (
                                self._extract_graph_link_keys(
                                    hop1_claims_by_id.get(hid, {}),
                                    hop1_parties_by_id.get(hid, []),
                                )
                            )
                            for v in h_vins:
                                if v not in seen_v:
                                    agg_vins.append(v)
                                    seen_v.add(v)
                            for a in h_addrs:
                                if a not in seen_a:
                                    agg_addresses.append(a)
                                    seen_a.add(a)
                            for prov in h_provs:
                                if prov not in seen_p:
                                    agg_providers.append(prov)
                                    seen_p.add(prov)
                            for ph in h_phones:
                                if ph not in seen_ph:
                                    agg_phones.append(ph)
                                    seen_ph.add(ph)
                            for em in h_emails:
                                if em not in seen_em:
                                    agg_emails.append(em)
                                    seen_em.add(em)

                        hop2_ids = self._query_related_ids_on_conn(
                            conn,
                            vins=agg_vins,
                            addresses=agg_addresses,
                            provider_names=agg_providers,
                            phones_unique=agg_phones,
                            emails_unique=agg_emails,
                            exclude_ids={claim_id} | hop1_ids,
                            # Over-fetch (×5) to account for duplicates across link-key
                            # types before the final deduplication and budget trim below.
                            limit=remaining * 5,
                        )
                        if len(hop2_ids) > remaining:
                            hop2_ids = set(sorted(hop2_ids)[:remaining])

                        if hop2_ids:
                            sorted_hop2 = sorted(hop2_ids)
                            h2_params: dict[str, Any] = {
                                f"id{i}": hid for i, hid in enumerate(sorted_hop2)
                            }
                            h2_in = ", ".join(f":id{i}" for i in range(len(sorted_hop2)))
                            for row in conn.execute(
                                text(f"SELECT * FROM claims WHERE id IN ({h2_in})"),
                                h2_params,
                            ).fetchall():
                                d = row_to_dict(row)
                                hop2_claims_by_id[d["id"]] = d
                            for row in conn.execute(
                                text(
                                    f"SELECT * FROM claim_parties WHERE claim_id IN ({h2_in})"
                                ),
                                h2_params,
                            ).fetchall():
                                p = row_to_dict(row)
                                hop2_parties_by_id.setdefault(p["claim_id"], []).append(p)

        # ── Build graph nodes and edges in-memory ──────────────────────────────
        nodes: list[dict[str, Any]] = [{"id": claim_id, "type": "claim"}]
        edges: list[dict[str, Any]] = []
        high_risk_link_count = 0

        # Hop-1 edges: root → hop1
        for h1_id in sorted(hop1_ids):
            h1_claim = hop1_claims_by_id.get(h1_id)
            if h1_claim is None:
                continue
            rtypes = resolve_edge_relations(
                root_vins,
                root_addresses,
                root_providers,
                root_phones,
                root_emails,
                h1_claim,
                hop1_parties_by_id.get(h1_id, []),
            )
            if not rtypes:
                continue
            nodes.append({"id": h1_id, "type": "claim"})
            edges.append({"from": claim_id, "to": h1_id, "relations": sorted(set(rtypes))})
            if _HIGH_RISK_RELATIONS & set(rtypes):
                high_risk_link_count += 1

        # Hop-2 edges: hop1 → hop2
        if effective_depth >= 2:
            added_hop2_edges: set[tuple[str, str]] = set()
            added_hop2_nodes: set[str] = set()
            for h2_id in sorted(hop2_ids):
                h2_claim = hop2_claims_by_id.get(h2_id)
                if h2_claim is None:
                    continue
                h2_parties = hop2_parties_by_id.get(h2_id, [])
                for h1_id in sorted(hop1_ids):
                    if (h1_id, h2_id) in added_hop2_edges:
                        continue
                    h1_claim = hop1_claims_by_id.get(h1_id)
                    if h1_claim is None:
                        continue
                    h1_vins, h1_addrs, h1_provs, h1_phones, h1_emails = (
                        self._extract_graph_link_keys(
                            h1_claim, hop1_parties_by_id.get(h1_id, [])
                        )
                    )
                    rtypes = resolve_edge_relations(
                        h1_vins,
                        h1_addrs,
                        h1_provs,
                        h1_phones,
                        h1_emails,
                        h2_claim,
                        h2_parties,
                    )
                    if not rtypes:
                        continue
                    if h2_id not in added_hop2_nodes:
                        nodes.append({"id": h2_id, "type": "claim"})
                        added_hop2_nodes.add(h2_id)
                    edges.append(
                        {"from": h1_id, "to": h2_id, "relations": sorted(set(rtypes))}
                    )
                    added_hop2_edges.add((h1_id, h2_id))
                    if _HIGH_RISK_RELATIONS & set(rtypes):
                        high_risk_link_count += 1

        edge_count = len(edges)
        node_count = len(nodes)
        dense_cluster_detected = edge_count >= 3 or high_risk_link_count >= 2
        signals: list[str] = []
        if dense_cluster_detected:
            signals.append("dense_cluster_detected")
        if high_risk_link_count >= 2:
            signals.append("high_risk_links")
        return {
            "claim_id": claim_id,
            "max_nodes": max_nodes,
            "node_count": node_count,
            "edge_count": edge_count,
            "high_risk_link_count": high_risk_link_count,
            "dense_cluster_detected": dense_cluster_detected,
            "signals": signals,
            "nodes": nodes,
            "edges": edges,
        }

    def get_relationship_index_snapshot(self, *, claim_id: str) -> dict[str, Any]:
        """Placeholder for future durable graph index implementation.

        Returns a migration-ready shape while current implementation derives data
        from normalized claims/parties tables.
        """
        return {
            "claim_id": claim_id,
            "source": "derived_from_claims_and_parties",
            "status": "not_materialized",
        }
