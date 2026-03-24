"""Mock ERP adapter — in-memory implementation for tests and development.

Simulates a repair/shop management system (ERP) with:
- Outbound: records all push calls (assignment, estimate, status) in memory.
- Inbound: returns a configurable queue of pending events for polling tests.
- Identity: provides an optional internal→ERP shop-ID mapping.

Thread-safe via a shared ``threading.Lock``.
"""

import copy
import threading
import uuid
from typing import Any

from claim_agent.adapters.base import ERPAdapter, VALID_ERP_EVENT_TYPES

# Re-export so callers can import from this module if needed
__all__ = ["MockERPAdapter", "VALID_ERP_EVENT_TYPES"]


class MockERPAdapter(ERPAdapter):
    """Fully in-memory ERP adapter for tests and development.

    All outbound pushes are recorded and can be inspected via the
    ``get_*`` helper methods.  Inbound events are seeded via
    ``seed_pending_event`` and drained by ``pull_pending_events``.

    An optional *shop_id_map* dict translates internal shop IDs to
    ERP-side identifiers (simulating the identity-mapping concern).
    """

    def __init__(
        self,
        shop_id_map: dict[str, str] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._shop_id_map: dict[str, str] = dict(shop_id_map or {})
        # Outbound records
        self._assignments: list[dict[str, Any]] = []
        self._estimate_updates: list[dict[str, Any]] = []
        self._status_updates: list[dict[str, Any]] = []
        # Inbound event queue (drained by pull_pending_events)
        self._pending_events: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def resolve_shop_id(self, internal_shop_id: str) -> str:
        with self._lock:
            return self._shop_id_map.get(internal_shop_id, internal_shop_id)

    # ------------------------------------------------------------------
    # Outbound – carrier → ERP
    # ------------------------------------------------------------------

    def push_repair_assignment(
        self,
        *,
        claim_id: str,
        shop_id: str,
        authorization_id: str | None,
        repair_amount: float | None,
        vehicle_info: dict[str, Any] | None,
    ) -> dict[str, Any]:
        erp_shop_id = self.resolve_shop_id(shop_id)
        ref = f"ERP-ASSIGN-{uuid.uuid4().hex[:8].upper()}"
        record: dict[str, Any] = {
            "erp_reference": ref,
            "claim_id": claim_id,
            "shop_id": shop_id,
            "erp_shop_id": erp_shop_id,
            "authorization_id": authorization_id,
            "repair_amount": repair_amount,
            "vehicle_info": copy.deepcopy(vehicle_info) if vehicle_info else None,
            "submission_status": "submitted",
        }
        with self._lock:
            self._assignments.append(record)
        return {"erp_reference": ref, "status": "submitted"}

    def push_estimate_update(
        self,
        *,
        claim_id: str,
        shop_id: str,
        authorization_id: str | None,
        estimate_amount: float,
        line_items: list[dict[str, Any]] | None,
        is_supplement: bool,
    ) -> dict[str, Any]:
        erp_shop_id = self.resolve_shop_id(shop_id)
        ref = f"ERP-EST-{uuid.uuid4().hex[:8].upper()}"
        record: dict[str, Any] = {
            "erp_reference": ref,
            "claim_id": claim_id,
            "shop_id": shop_id,
            "erp_shop_id": erp_shop_id,
            "authorization_id": authorization_id,
            "estimate_amount": round(float(estimate_amount), 2),
            "line_items": copy.deepcopy(line_items) if line_items else None,
            "is_supplement": is_supplement,
            "submission_status": "submitted",
        }
        with self._lock:
            self._estimate_updates.append(record)
        return {"erp_reference": ref, "status": "submitted"}

    def push_repair_status(
        self,
        *,
        claim_id: str,
        shop_id: str,
        authorization_id: str | None,
        status: str,
        notes: str | None,
    ) -> dict[str, Any]:
        erp_shop_id = self.resolve_shop_id(shop_id)
        ref = f"ERP-STATUS-{uuid.uuid4().hex[:8].upper()}"
        record: dict[str, Any] = {
            "erp_reference": ref,
            "claim_id": claim_id,
            "shop_id": shop_id,
            "erp_shop_id": erp_shop_id,
            "authorization_id": authorization_id,
            "status": status,
            "notes": notes,
            "submission_status": "submitted",
        }
        with self._lock:
            self._status_updates.append(record)
        return {"erp_reference": ref, "status": "submitted"}

    # ------------------------------------------------------------------
    # Inbound – ERP → carrier (polling)
    # ------------------------------------------------------------------

    def pull_pending_events(
        self,
        *,
        shop_id: str | None = None,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return and drain all seeded inbound events.

        Events are filtered by *shop_id* when provided (matching on the
        internal ``shop_id`` field).  The *since* filter is evaluated
        lexicographically against the ``occurred_at`` ISO-8601 string.
        """
        with self._lock:
            events = list(self._pending_events)
            self._pending_events = []

        filtered: list[dict[str, Any]] = []
        non_matching: list[dict[str, Any]] = []
        for evt in events:
            if shop_id is not None and evt.get("shop_id") != shop_id:
                non_matching.append(evt)
                continue
            if since is not None and evt.get("occurred_at", "") <= since:
                non_matching.append(evt)
                continue
            filtered.append(copy.deepcopy(evt))
        
        with self._lock:
            self._pending_events.extend(non_matching)
        
        return filtered

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def seed_pending_event(self, event: dict[str, Any]) -> None:
        """Enqueue an inbound ERP event to be returned by the next poll.

        The *event* dict must include at minimum:
        ``event_type``, ``claim_id``, ``shop_id``, ``erp_event_id``,
        ``occurred_at``.
        """
        with self._lock:
            self._pending_events.append(copy.deepcopy(event))

    def get_pushed_assignments(self) -> list[dict[str, Any]]:
        """Return all outbound assignment records (copy; does not drain)."""
        with self._lock:
            return [copy.deepcopy(r) for r in self._assignments]

    def get_pushed_estimate_updates(self) -> list[dict[str, Any]]:
        """Return all outbound estimate/supplement records (copy)."""
        with self._lock:
            return [copy.deepcopy(r) for r in self._estimate_updates]

    def get_pushed_status_updates(self) -> list[dict[str, Any]]:
        """Return all outbound repair-status records (copy)."""
        with self._lock:
            return [copy.deepcopy(r) for r in self._status_updates]

    def clear_all(self) -> None:
        """Reset all outbound records and inbound event queue."""
        with self._lock:
            self._assignments.clear()
            self._estimate_updates.clear()
            self._status_updates.clear()
            self._pending_events.clear()
