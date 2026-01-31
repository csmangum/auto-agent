"""Fraud detection tools: pattern analysis, cross-reference, and fraud assessment."""

import json

from crewai.tools import tool

from claim_agent.tools.logic import (
    analyze_claim_patterns_impl,
    cross_reference_fraud_indicators_impl,
    perform_fraud_assessment_impl,
)


@tool("Analyze Claim Patterns")
def analyze_claim_patterns(claim_data: str, vin: str = "") -> str:
    """Analyze claim for suspicious patterns including multiple claims, timing anomalies, and staged accident indicators.
    
    Args:
        claim_data: JSON string of claim input with fields like vin, incident_date, incident_description, damage_description.
        vin: Optional VIN to analyze (if not in claim_data).
    
    Returns:
        JSON with pattern_analysis including patterns_detected, timing_flags, claim_history, risk_factors, and pattern_score.
    """
    data = {}
    if isinstance(claim_data, str) and claim_data.strip():
        try:
            data = json.loads(claim_data)
        except json.JSONDecodeError:
            data = {}
    
    return analyze_claim_patterns_impl(data, vin if vin else None)


@tool("Cross Reference Fraud Indicators")
def cross_reference_fraud_indicators(claim_data: str) -> str:
    """Cross-reference claim against known fraud indicators database.
    
    Checks for:
    - Fraud keywords in incident and damage descriptions
    - Damage estimate vs vehicle value mismatches
    - Prior fraud flags on VIN or policy
    
    Args:
        claim_data: JSON string of claim input.
    
    Returns:
        JSON with fraud_keywords_found, database_matches, risk_level, cross_reference_score, and recommendations.
    """
    data = {}
    if isinstance(claim_data, str) and claim_data.strip():
        try:
            data = json.loads(claim_data)
        except json.JSONDecodeError:
            data = {}
    
    return cross_reference_fraud_indicators_impl(data)


@tool("Perform Fraud Assessment")
def perform_fraud_assessment(
    claim_data: str,
    pattern_analysis: str = "",
    cross_reference: str = "",
) -> str:
    """Perform comprehensive fraud assessment combining pattern analysis and cross-reference results.
    
    Args:
        claim_data: JSON string of claim input.
        pattern_analysis: Optional JSON string from analyze_claim_patterns result.
        cross_reference: Optional JSON string from cross_reference_fraud_indicators result.
    
    Returns:
        JSON with fraud_score, fraud_likelihood (low/medium/high/critical), fraud_indicators list,
        recommended_action, should_block flag, and siu_referral flag.
    """
    data = {}
    if isinstance(claim_data, str) and claim_data.strip():
        try:
            data = json.loads(claim_data)
        except json.JSONDecodeError:
            data = {}
    
    patterns = None
    if pattern_analysis and str(pattern_analysis).strip():
        try:
            patterns = json.loads(pattern_analysis)
        except json.JSONDecodeError:
            patterns = None
    
    xref = None
    if cross_reference and str(cross_reference).strip():
        try:
            xref = json.loads(cross_reference)
        except json.JSONDecodeError:
            xref = None
    
    return perform_fraud_assessment_impl(data, patterns, xref)


@tool("Generate Fraud Report")
def generate_fraud_report(
    claim_id: str,
    fraud_likelihood: str,
    fraud_score: str,
    fraud_indicators: str,
    recommended_action: str,
    siu_referral: str = "false",
    should_block: str = "false",
) -> str:
    """Generate a human-readable fraud assessment report.
    
    Args:
        claim_id: The claim ID.
        fraud_likelihood: low, medium, high, or critical.
        fraud_score: Numeric fraud risk score as string.
        fraud_indicators: JSON array of fraud indicator strings.
        recommended_action: Recommended action text.
        siu_referral: 'true' or 'false' for SIU referral.
        should_block: 'true' or 'false' for claim blocking.
    
    Returns:
        Formatted fraud assessment report string.
    """
    try:
        indicators = json.loads(fraud_indicators) if fraud_indicators else []
    except json.JSONDecodeError:
        indicators = []
    
    try:
        score = int(float(fraud_score)) if fraud_score else 0
    except (ValueError, TypeError):
        score = 0
    
    is_siu_referral = str(siu_referral).strip().lower() in ("true", "1", "yes")
    is_blocked = str(should_block).strip().lower() in ("true", "1", "yes")
    
    # Build report
    lines = [
        "=" * 60,
        f"FRAUD ASSESSMENT REPORT — Claim {claim_id}",
        "=" * 60,
        "",
        f"Fraud Likelihood: {fraud_likelihood.upper()}",
        f"Risk Score: {score}",
        "",
        f"SIU Referral Required: {'YES' if is_siu_referral else 'No'}",
        f"Claim Blocked: {'YES - DO NOT PROCESS' if is_blocked else 'No'}",
        "",
        "Fraud Indicators Detected:",
    ]
    
    if indicators:
        for i, indicator in enumerate(indicators, 1):
            lines.append(f"  {i}. {indicator}")
    else:
        lines.append("  None detected")
    
    lines.extend([
        "",
        "Recommended Action:",
        f"  {recommended_action}",
        "",
        "=" * 60,
    ])
    
    return "\n".join(lines)
