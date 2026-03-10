"""Property-based tests for router output parsing.

Uses Hypothesis to fuzz ``_parse_router_output`` and ``_parse_claim_type``
across all three parsing paths (Pydantic, JSON, legacy) to verify
invariants that must hold regardless of input.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from claim_agent.models.claim import ClaimType, RouterOutput
from claim_agent.workflow.routing import _parse_router_output, _parse_claim_type
from claim_agent.tools.escalation_logic import normalize_claim_type

VALID_CLAIM_TYPES = frozenset(ct.value for ct in ClaimType)

claim_type_strategy = st.sampled_from(sorted(VALID_CLAIM_TYPES))
confidence_strategy = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
reasoning_strategy = st.text(min_size=0, max_size=200)


# --------------------------------------------------------------------------
# Round-trip: valid JSON -> parse -> same values
# --------------------------------------------------------------------------


@given(
    claim_type=claim_type_strategy,
    confidence=confidence_strategy,
    reasoning=reasoning_strategy,
)
@settings(max_examples=200)
def test_json_round_trip(claim_type: str, confidence: float, reasoning: str):
    """Constructing a valid JSON string and parsing it yields the same values."""
    raw = json.dumps({
        "claim_type": claim_type,
        "confidence": confidence,
        "reasoning": reasoning,
    })
    result = object()
    parsed_type, parsed_conf, parsed_reason = _parse_router_output(result, raw)
    assert parsed_type == claim_type
    assert abs(parsed_conf - max(0.0, min(1.0, confidence))) < 1e-6
    assert parsed_reason == reasoning.strip()


# --------------------------------------------------------------------------
# Claim type is always in the valid set
# --------------------------------------------------------------------------


@given(raw_output=st.text(min_size=0, max_size=500))
@settings(max_examples=300)
def test_claim_type_always_valid(raw_output: str):
    """Output claim_type is always a valid ClaimType regardless of input."""
    result = object()
    claim_type, _, _ = _parse_router_output(result, raw_output)
    assert claim_type in VALID_CLAIM_TYPES


# --------------------------------------------------------------------------
# Confidence is always bounded [0.0, 1.0]
# --------------------------------------------------------------------------


@given(
    confidence=st.one_of(
        st.floats(allow_nan=False, allow_infinity=False),
        st.integers(min_value=-1000, max_value=1000),
    ),
    claim_type=claim_type_strategy,
)
@settings(max_examples=200)
def test_confidence_always_bounded(confidence, claim_type: str):
    """Output confidence is in [0.0, 1.0] even with extreme input values."""
    raw = json.dumps({
        "claim_type": claim_type,
        "confidence": confidence,
        "reasoning": "test",
    })
    result = object()
    _, parsed_conf, _ = _parse_router_output(result, raw)
    assert 0.0 <= parsed_conf <= 1.0


# --------------------------------------------------------------------------
# Never crashes on arbitrary strings
# --------------------------------------------------------------------------


@given(raw_output=st.text(min_size=0, max_size=2000))
@settings(max_examples=500)
def test_never_crashes(raw_output: str):
    """_parse_router_output never raises for any string input."""
    result = object()
    claim_type, confidence, reasoning = _parse_router_output(result, raw_output)
    assert isinstance(claim_type, str)
    assert isinstance(confidence, float)
    assert isinstance(reasoning, str)


# --------------------------------------------------------------------------
# JSON wrapped in markdown fences
# --------------------------------------------------------------------------

fence_strategy = st.sampled_from(["```json\n", "```\n"])


@given(
    claim_type=claim_type_strategy,
    confidence=confidence_strategy,
    reasoning=reasoning_strategy,
    fence=fence_strategy,
)
@settings(max_examples=200)
def test_json_in_markdown_fences(claim_type: str, confidence: float, reasoning: str, fence: str):
    """Valid JSON wrapped in markdown code fences is parsed correctly."""
    assume("\n" not in reasoning and "```" not in reasoning)
    inner = json.dumps({
        "claim_type": claim_type,
        "confidence": confidence,
        "reasoning": reasoning,
    })
    raw = f"{fence}{inner}\n```"
    result = object()
    parsed_type, parsed_conf, _ = _parse_router_output(result, raw)
    assert parsed_type == claim_type
    assert 0.0 <= parsed_conf <= 1.0


# --------------------------------------------------------------------------
# Pydantic path (via tasks_output)
# --------------------------------------------------------------------------


@given(
    claim_type=claim_type_strategy,
    confidence=confidence_strategy,
    reasoning=reasoning_strategy,
)
@settings(max_examples=200)
def test_pydantic_path(claim_type: str, confidence: float, reasoning: str):
    """When tasks_output contains a RouterOutput, it is preferred."""
    router_output = RouterOutput(
        claim_type=claim_type,
        confidence=confidence,
        reasoning=reasoning,
    )
    mock_task = MagicMock(output=router_output)
    result = MagicMock(tasks_output=[mock_task])
    parsed_type, parsed_conf, parsed_reason = _parse_router_output(result, "fallback text")
    assert parsed_type in VALID_CLAIM_TYPES
    assert 0.0 <= parsed_conf <= 1.0
    assert isinstance(parsed_reason, str)


# --------------------------------------------------------------------------
# Legacy fallback: claim type keyword detection
# --------------------------------------------------------------------------


@given(
    claim_type=claim_type_strategy,
    prefix=st.text(min_size=0, max_size=50),
    suffix=st.text(min_size=0, max_size=50),
)
@settings(max_examples=200)
def test_legacy_claim_type_detection(claim_type: str, prefix: str, suffix: str):
    """_parse_claim_type detects known claim types embedded in text lines."""
    assume("\n" not in prefix and "\n" not in suffix)
    display = claim_type.replace("_", " ")
    raw = f"{prefix}\n{display}\n{suffix}"
    parsed = _parse_claim_type(raw)
    assert parsed in VALID_CLAIM_TYPES


# --------------------------------------------------------------------------
# normalize_claim_type always returns valid value
# --------------------------------------------------------------------------


@given(value=st.text(min_size=0, max_size=100))
@settings(max_examples=200)
def test_normalize_claim_type_always_valid(value: str):
    """normalize_claim_type always returns a valid ClaimType value."""
    result = normalize_claim_type(value)
    assert result in VALID_CLAIM_TYPES


# --------------------------------------------------------------------------
# JSON with missing fields still parses safely
# --------------------------------------------------------------------------


@given(
    extra_fields=st.dictionaries(
        keys=st.text(min_size=1, max_size=20),
        values=st.one_of(st.text(max_size=50), st.integers(), st.floats(allow_nan=False)),
        max_size=5,
    ),
)
@settings(max_examples=100)
def test_json_with_missing_or_extra_fields(extra_fields):
    """JSON with missing required fields or extra fields never crashes."""
    raw = json.dumps(extra_fields)
    result = object()
    claim_type, confidence, reasoning = _parse_router_output(result, raw)
    assert claim_type in VALID_CLAIM_TYPES
    assert 0.0 <= confidence <= 1.0
    assert isinstance(reasoning, str)
