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
        assert SUPPORTED_STATES == ("California", "Texas", "Florida", "New York")

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
