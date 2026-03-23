"""Shared async entry for supplemental damage workflow (adjuster + repair portal)."""

from __future__ import annotations

import asyncio
from typing import Any

from claim_agent.context import ClaimContext
from claim_agent.workflow.supplemental_orchestrator import run_supplemental_workflow


async def execute_supplemental_request(
    *,
    claim_id: str,
    supplemental_damage_description: str,
    reported_by: str | None,
    ctx: ClaimContext,
) -> dict[str, Any]:
    """Run supplemental workflow. Raises ClaimNotFoundError or ValueError from orchestrator."""
    supplemental_data = {
        "claim_id": claim_id,
        "supplemental_damage_description": supplemental_damage_description,
        "reported_by": reported_by,
    }
    return await asyncio.to_thread(
        run_supplemental_workflow,
        supplemental_data,
        ctx=ctx,
    )
