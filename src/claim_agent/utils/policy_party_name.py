"""Resolve display names from policy party dicts (named insured, drivers).

Adapters may use ``name``, ``full_name``, or ``display_name``. This module
provides a single precedence order for masking (policy query) and verification
so behavior does not drift.
"""

from __future__ import annotations


def get_policy_party_display_name(item: dict) -> str | None:
    """Return the best display name from a policy party dict, or None.

    Precedence: ``name``, then ``full_name``, then ``display_name``.
    """
    candidate = item.get("name") or item.get("full_name") or item.get("display_name")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return None
