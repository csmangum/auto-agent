"""Sanity checks for shared API HTTP hint constants."""

from claim_agent.api import http_constants as hc


def test_claim_already_processing_retry_after_is_string_seconds() -> None:
    assert hc.CLAIM_ALREADY_PROCESSING_RETRY_AFTER == "30"


def test_background_queue_full_retry_after_is_string_seconds() -> None:
    assert hc.BACKGROUND_QUEUE_FULL_RETRY_AFTER == "60"


def test_background_queue_full_detail_is_non_empty() -> None:
    assert isinstance(hc.BACKGROUND_QUEUE_FULL_DETAIL, str)
    assert len(hc.BACKGROUND_QUEUE_FULL_DETAIL.strip()) > 0
