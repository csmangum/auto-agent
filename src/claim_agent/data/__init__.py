"""Shared data access layer for JSON-backed mock and compliance data."""

from claim_agent.data.loader import (
    get_compliance_retention_years,
    load_california_compliance,
    load_mock_db,
)

__all__ = [
    "get_compliance_retention_years",
    "load_california_compliance",
    "load_mock_db",
]
