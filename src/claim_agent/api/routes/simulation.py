"""Simulation API routes.

This router currently does not expose role metadata, because the frontend
simulation UI defines role capabilities locally and does not call a backend
endpoint yet. To avoid two sources of truth and configuration drift, add
a ``/simulation/roles`` endpoint here only when the UI is wired to consume it.
"""

from fastapi import APIRouter

router = APIRouter(tags=["simulation"])
