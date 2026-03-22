"""Mock reverse-image adapter -- deterministic results for development/testing."""

from pathlib import Path
from typing import Any

from claim_agent.adapters.base import ReverseImageAdapter

# Deterministic match set returned for every query in mock mode.
# Using a stable fixture avoids network calls and keeps tests reproducible.
_MOCK_MATCHES: list[dict[str, Any]] = [
    {
        "url": "https://stock.example.com/images/car-damage-123.jpg",
        "match_score": 0.91,
        "source_label": "stock_photo_site",
        "title": "Generic car damage stock photo",
        "page_fetched_at": "2024-01-15T00:00:00Z",
    },
    {
        "url": "https://social.example.com/posts/99887766",
        "match_score": 0.74,
        "source_label": "social_media",
        "title": "Post from prior incident",
        "page_fetched_at": "2024-01-15T00:00:00Z",
    },
]


class MockReverseImageAdapter(ReverseImageAdapter):
    """Mock reverse-image adapter that returns deterministic results without network access.

    Always returns :data:`_MOCK_MATCHES` regardless of the image supplied.
    Suitable for unit tests and development environments.
    """

    def match_web_occurrences(self, image: bytes | Path) -> list[dict[str, Any]]:
        """Return fixed deterministic matches (no network call is made)."""
        return list(_MOCK_MATCHES)
