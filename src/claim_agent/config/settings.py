"""Centralized configuration - delegates to Pydantic Settings model.

All configuration is loaded via get_settings(). These functions provide
backward-compatible access during migration. Prefer get_settings() directly.
"""

from claim_agent.config import get_settings
from claim_agent.config.settings_model import ApiKeyEntry


def get_coverage_config() -> dict:
    """FNOL coverage verification settings."""
    s = get_settings().coverage
    return {
        "enabled": s.enabled,
        "deny_when_deductible_exceeds_damage": s.deny_when_deductible_exceeds_damage,
        "require_incident_location": s.require_incident_location,
    }


def get_router_config() -> dict:
    """Router classification thresholds and behavior."""
    s = get_settings().router
    return {
        "confidence_threshold": s.confidence_threshold,
        "validation_enabled": s.validation_enabled,
    }


def get_escalation_config() -> dict:
    """Escalation thresholds for human-in-the-loop review."""
    s = get_settings().escalation
    return {
        "confidence_threshold": s.confidence_threshold,
        "high_value_threshold": s.high_value_threshold,
        "similarity_ambiguous_range": s.similarity_ambiguous_range,
        "fraud_damage_vs_value_ratio": s.fraud_damage_vs_value_ratio,
        "vin_claims_days": s.vin_claims_days,
        "confidence_decrement_per_pattern": s.confidence_decrement_per_pattern,
        "description_overlap_threshold": s.description_overlap_threshold,
        "use_agent": s.use_agent,
    }


def get_reserve_config() -> dict:
    """Reserve management: authority limits and FNOL behavior."""
    s = get_settings().reserve
    return {
        "adjuster_limit": s.adjuster_limit,
        "supervisor_limit": s.supervisor_limit,
        "executive_limit": s.executive_limit,
        "initial_reserve_from_estimated_damage": s.initial_reserve_from_estimated_damage,
        "close_settle_adequacy_gate": s.close_settle_adequacy_gate,
    }


def get_payment_config() -> dict:
    """Payment authority limits: adjuster, supervisor, executive."""
    s = get_settings().payment
    return {
        "adjuster_limit": s.adjuster_limit,
        "supervisor_limit": s.supervisor_limit,
        "executive_limit": s.executive_limit,
        "auto_record_from_settlement": s.auto_record_from_settlement,
    }


def get_fraud_config() -> dict:
    """Fraud detection thresholds and scores."""
    s = get_settings().fraud
    return {
        "multiple_claims_days": s.multiple_claims_days,
        "multiple_claims_threshold": s.multiple_claims_threshold,
        "fraud_keyword_score": s.fraud_keyword_score,
        "multiple_claims_score": s.multiple_claims_score,
        "timing_anomaly_score": s.timing_anomaly_score,
        "damage_mismatch_score": s.damage_mismatch_score,
        "high_risk_threshold": s.high_risk_threshold,
        "medium_risk_threshold": s.medium_risk_threshold,
        "critical_risk_threshold": s.critical_risk_threshold,
        "critical_indicator_count": s.critical_indicator_count,
        "velocity_window_days": s.velocity_window_days,
        "velocity_claim_threshold": s.velocity_claim_threshold,
        "velocity_score": s.velocity_score,
        "geographic_anomaly_score": s.geographic_anomaly_score,
        "provider_ring_threshold": s.provider_ring_threshold,
        "provider_ring_score": s.provider_ring_score,
        "graph_max_depth": s.graph_max_depth,
        "graph_max_nodes": s.graph_max_nodes,
        "graph_cluster_score": s.graph_cluster_score,
        "graph_high_risk_link_threshold": s.graph_high_risk_link_threshold,
        "graph_high_risk_score": s.graph_high_risk_score,
        "staged_pattern_score": s.staged_pattern_score,
        "claimsearch_match_threshold": s.claimsearch_match_threshold,
        "claimsearch_match_score": s.claimsearch_match_score,
        "photo_exif_anomaly_score": s.photo_exif_anomaly_score,
        "photo_gps_far_from_incident_score": s.photo_gps_far_from_incident_score,
        "photo_gps_incident_max_distance": s.photo_gps_incident_max_distance,
        "photo_gps_incident_distance_unit": s.photo_gps_incident_distance_unit,
    }


def get_api_keys_config() -> dict[str, str]:
    """API keys mapping key -> role."""
    return get_settings().auth.api_keys.copy()


def get_api_key_entries() -> dict[str, ApiKeyEntry]:
    """API_KEYS entries: key -> ApiKeyEntry(role, optional identity)."""
    return get_settings().auth.api_key_entries.copy()


def get_jwt_secret() -> str | None:
    """JWT secret for verifying Bearer tokens. None if not configured."""
    return get_settings().auth.jwt_secret


def get_jwt_access_ttl_seconds() -> int:
    """Access JWT TTL in seconds."""
    return get_settings().auth.jwt_access_ttl_seconds


def get_jwt_refresh_ttl_seconds() -> int:
    """Refresh token (opaque) TTL in seconds."""
    return get_settings().auth.jwt_refresh_ttl_seconds


def get_mask_pii() -> bool:
    """Whether to mask PII (policy_number, vin) in logs and metrics."""
    return get_settings().logging.mask_pii


def get_retention_period_years() -> int:
    """Retention period in years from env, compliance config, or default (5)."""
    return get_settings().retention_period_years


def get_retention_purge_after_archive_years() -> int:
    """Years after archived_at before purge (anonymize + purged status). Default 2."""
    return get_settings().retention_purge_after_archive_years


def get_audit_log_retention_years_after_purge() -> int | None:
    """Years after purged_at for audit log export/purge eligibility; None if unset."""
    return get_settings().audit_log_retention_years_after_purge


def is_audit_log_purge_enabled() -> bool:
    """True when AUDIT_LOG_PURGE_ENABLED allows audit-log-purge deletes."""
    return get_settings().audit_log_purge_enabled


def get_retention_export_config() -> dict:
    """Cold-storage export settings (S3/Glacier pipeline)."""
    s = get_settings().retention_export
    return {
        "enabled": s.enabled,
        "s3_bucket": s.s3_bucket,
        "s3_prefix": s.s3_prefix,
        "s3_endpoint": s.s3_endpoint,
        "s3_storage_class": s.s3_storage_class,
        "encryption": s.encryption,
        "kms_key_id": s.kms_key_id,
    }


def get_retention_by_state() -> dict[str, int]:
    """State-specific retention periods (years). Empty = use default only."""
    return get_settings().get_retention_by_state()


def get_purge_after_archive_by_state() -> dict[str, int]:
    """State-specific purge-after-archive periods (years). Empty = use global only."""
    return get_settings().get_purge_after_archive_by_state()


def get_crew_verbose() -> bool:
    """Whether CrewAI runs in verbose mode."""
    return get_settings().crew_verbose


def get_webhook_config() -> dict:
    """Webhook configuration for outbound notifications."""
    s = get_settings().webhook
    return {
        "urls": s.urls.copy(),
        "secret": s.secret,
        "max_retries": s.max_retries,
        "enabled": s.enabled,
        "shop_url": s.shop_url,
        "dead_letter_path": s.dead_letter_path,
    }


def get_llm_cost_alert_config() -> dict:
    """LLM cost alert configuration."""
    s = get_settings().llm_cost_alert
    return {
        "threshold_usd": s.threshold_usd,
        "webhook_url": s.webhook_url,
    }


def get_notification_config() -> dict:
    """Claimant notification configuration (email/SMS)."""
    s = get_settings().notification
    return {
        "email_enabled": s.email_enabled,
        "sms_enabled": s.sms_enabled,
        "sendgrid_api_key": s.sendgrid_api_key.get_secret_value(),
        "sendgrid_from_email": s.sendgrid_from_email,
        "twilio_account_sid": s.twilio_account_sid,
        "twilio_auth_token": s.twilio_auth_token.get_secret_value(),
        "twilio_from_phone": s.twilio_from_phone,
    }


def get_adapter_backend(adapter_name: str) -> str:
    """Return the configured backend for *adapter_name* (default: mock)."""
    return get_settings().get_adapter_backend(adapter_name)


def get_mock_crew_config() -> dict:
    """Mock Crew configuration (enabled, seed)."""
    s = get_settings().mock_crew
    return {
        "enabled": s.enabled,
        "seed": s.seed,
    }


def get_mock_claimant_config() -> dict:
    """Mock Claimant configuration (enabled, response_strategy)."""
    s = get_settings().mock_claimant
    return {
        "enabled": s.enabled,
        "response_strategy": s.response_strategy.value,
    }


def get_chat_config() -> dict:
    """Chat agent configuration."""
    s = get_settings().chat
    return {
        "max_tool_rounds": s.max_tool_rounds,
        "max_message_history": s.max_message_history,
        "system_prompt_override": s.system_prompt_override,
    }


def get_portal_config() -> dict:
    """Claimant portal configuration."""
    s = get_settings().portal
    return {
        "enabled": s.enabled,
        "verification_mode": s.verification_mode,
        "token_expiry_days": s.token_expiry_days,
    }


def get_mock_image_config() -> dict:
    """Mock image generator configuration."""
    s = get_settings().mock_image
    return {
        "generator_enabled": s.generator_enabled,
        "model": s.model,
        "vision_analysis_source": s.vision_analysis_source,
    }


# Re-export as module-level names for existing imports (lazy via __getattr__)
def __getattr__(name: str):
    if name == "DEFAULT_BASE_VALUE":
        return get_settings().valuation.default_base_value
    if name == "DEPRECIATION_PER_YEAR":
        return get_settings().valuation.depreciation_per_year
    if name == "MIN_VEHICLE_VALUE":
        return get_settings().valuation.min_vehicle_value
    if name == "DEFAULT_DEDUCTIBLE":
        return get_settings().valuation.default_deductible
    if name == "MIN_PAYOUT_VEHICLE_VALUE":
        return get_settings().valuation.min_payout_vehicle_value
    if name == "PARTIAL_LOSS_THRESHOLD":
        return get_settings().partial_loss.threshold
    if name == "LABOR_HOURS_RNI_PER_PART":
        return get_settings().partial_loss.labor_hours_rni_per_part
    if name == "LABOR_HOURS_PAINT_BODY":
        return get_settings().partial_loss.labor_hours_paint_body
    if name == "LABOR_HOURS_MIN":
        return get_settings().partial_loss.labor_hours_min
    if name == "DUPLICATE_SIMILARITY_THRESHOLD":
        return get_settings().duplicate_similarity_threshold
    if name == "DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE":
        return get_settings().duplicate_similarity_threshold_high_value
    if name == "DUPLICATE_DAYS_WINDOW":
        return get_settings().duplicate_days_window
    if name == "HIGH_VALUE_DAMAGE_THRESHOLD":
        return get_settings().high_value_damage_threshold
    if name == "HIGH_VALUE_VEHICLE_THRESHOLD":
        return get_settings().high_value_vehicle_threshold
    if name == "PRE_ROUTING_FRAUD_DAMAGE_RATIO":
        return get_settings().pre_routing_fraud_damage_ratio
    if name == "ESCALATION_SLA_HOURS_CRITICAL":
        return get_settings().escalation.sla_hours_critical
    if name == "ESCALATION_SLA_HOURS_HIGH":
        return get_settings().escalation.sla_hours_high
    if name == "ESCALATION_SLA_HOURS_MEDIUM":
        return get_settings().escalation.sla_hours_medium
    if name == "ESCALATION_SLA_HOURS_LOW":
        return get_settings().escalation.sla_hours_low
    if name == "MAX_TOKENS_PER_CLAIM":
        return get_settings().max_tokens_per_claim
    if name == "MAX_LLM_CALLS_PER_CLAIM":
        return get_settings().max_llm_calls_per_claim
    if name == "AFTER_ACTION_NOTE_MAX_TOKENS":
        return get_settings().after_action_note_max_tokens
    if name == "ADAPTER_ENV_KEYS":
        from claim_agent.config.settings_model import ADAPTER_ENV_KEYS
        return ADAPTER_ENV_KEYS
    if name == "VALID_ADAPTER_BACKENDS":
        from claim_agent.config.settings_model import VALID_ADAPTER_BACKENDS
        return VALID_ADAPTER_BACKENDS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
