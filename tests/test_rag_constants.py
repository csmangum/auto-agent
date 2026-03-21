"""Tests for RAG constants and helpers."""

import pytest

from claim_agent.rag.constants import (
    DEFAULT_STATE,
    SUPPORTED_STATES,
    normalize_state,
)


class TestRAGConstants:
    """Test RAG module constants."""

    def test_supported_states(self):
        assert SUPPORTED_STATES == (
            "California",
            "Texas",
            "Florida",
            "New York",
            "Georgia",
            "New Jersey",
            "Pennsylvania",
            "Illinois",
        )

    def test_default_state(self):
        assert DEFAULT_STATE == "California"


class TestNormalizeState:
    """Test normalize_state function."""

    def test_valid_california(self):
        assert normalize_state("California") == "California"
        assert normalize_state("california") == "California"
        assert normalize_state("CALIFORNIA") == "California"

    def test_valid_texas(self):
        assert normalize_state("texas") == "Texas"
        assert normalize_state("  Texas  ") == "Texas"

    def test_valid_florida(self):
        assert normalize_state("florida") == "Florida"

    def test_valid_new_york(self):
        assert normalize_state("new york") == "New York"

    def test_valid_georgia(self):
        assert normalize_state("georgia") == "Georgia"
        assert normalize_state("Georgia") == "Georgia"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="State cannot be empty"):
            normalize_state("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="Unsupported state"):
            normalize_state("   ")

    def test_unsupported_state_raises(self):
        with pytest.raises(ValueError, match="Unsupported state"):
            normalize_state("Nevada")
        with pytest.raises(ValueError, match="Supported"):
            normalize_state("invalid")

    def test_whitespace_stripped(self):
        assert normalize_state("  California  ") == "California"
        assert normalize_state("\tTexas\t") == "Texas"

    def test_accepts_state_abbreviations(self):
        """State abbreviations map to canonical names."""
        assert normalize_state("CA") == "California"
        assert normalize_state("ca") == "California"
        assert normalize_state("TX") == "Texas"
        assert normalize_state("FL") == "Florida"
        assert normalize_state("NY") == "New York"
        assert normalize_state("GA") == "Georgia"
        assert normalize_state("NJ") == "New Jersey"
        assert normalize_state("PA") == "Pennsylvania"
        assert normalize_state("IL") == "Illinois"
