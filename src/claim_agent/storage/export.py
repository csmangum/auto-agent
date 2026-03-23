"""Cold-storage export pipeline for retention purge.

Writes a JSON manifest (claim data + audit log summary) to S3/Glacier before
or instead of in-place PII anonymisation.  Designed to:

- Reuse the S3 credentials / endpoint already configured for attachment storage.
- Be idempotent: if ``cold_storage_exported_at`` is already set on the claim,
  the export is skipped and the existing key is returned.
- Apply server-side encryption and a configurable storage class so that the
  bucket lifecycle can transition objects to Glacier automatically.

Environment variables (set via :class:`~claim_agent.config.settings_model.RetentionExportConfig`):

``RETENTION_EXPORT_ENABLED``
    Must be ``true`` to allow exports.
``RETENTION_EXPORT_S3_BUCKET``
    Destination bucket (required when enabled).
``RETENTION_EXPORT_S3_PREFIX``
    Key prefix inside the bucket (default: ``retention-exports``).
``RETENTION_EXPORT_S3_ENDPOINT``
    Optional endpoint URL for S3-compatible storage (MinIO, etc.).
``RETENTION_EXPORT_S3_STORAGE_CLASS``
    Storage class applied to the object (default: ``GLACIER_IR``).
``RETENTION_EXPORT_ENCRYPTION``
    Server-side encryption: ``AES256`` (default) or ``aws:kms``.
``RETENTION_EXPORT_KMS_KEY_ID``
    KMS key ARN/alias when ``encryption=aws:kms``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claim_agent.config.settings_model import RetentionExportConfig
    from claim_agent.db.repository import ClaimRepository

_log = logging.getLogger(__name__)

# Audit log rows included in the manifest (capped to avoid unbounded payloads).
AUDIT_LOG_MAX_ROWS = 1_000


def build_claim_manifest(
    claim_data: dict[str, Any],
    audit_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a JSON-serialisable export manifest for a single claim.

    The manifest intentionally includes the *pre-anonymisation* claim data so
    that compliance teams can recover it from cold storage if required.

    Args:
        claim_data: Full claim row as a dict (from the database).
        audit_rows: Audit log rows for this claim (may be truncated).

    Returns:
        A dict with the following keys:

        - ``schema_version`` (str): Always ``"1.0"``.
        - ``exported_at`` (str): ISO 8601 UTC timestamp of the export.
        - ``claim`` (dict): Full claim row (pre-anonymisation).
        - ``audit_log`` (list[dict]): Up to :data:`AUDIT_LOG_MAX_ROWS` audit entries.
        - ``audit_log_truncated`` (bool): ``True`` when the original list exceeded the cap.
    """
    return {
        "schema_version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "claim": claim_data,
        "audit_log": audit_rows[:AUDIT_LOG_MAX_ROWS],
        "audit_log_truncated": len(audit_rows) > AUDIT_LOG_MAX_ROWS,
    }


def export_claim_to_cold_storage(
    claim_id: str,
    repo: "ClaimRepository",
    config: "RetentionExportConfig",
    *,
    actor_id: str = "retention",
) -> str:
    """Export a single claim to S3/Glacier cold storage.

    The function is idempotent: if the claim already has
    ``cold_storage_exported_at`` set, it returns the existing
    ``cold_storage_export_key`` without re-uploading.

    Args:
        claim_id: The claim to export.
        repo: Repository instance (used for data fetch + mark_claim_exported).
        config: :class:`~claim_agent.config.settings_model.RetentionExportConfig`.
        actor_id: Actor identifier written to the audit log.

    Returns:
        The S3 object key of the exported manifest.

    Raises:
        ValueError: If export is disabled or the bucket is not configured.
        RuntimeError: If the boto3 S3 upload fails.
    """
    if not config.enabled:
        raise ValueError(
            "Cold-storage export is disabled. Set RETENTION_EXPORT_ENABLED=true."
        )
    if not config.s3_bucket:
        raise ValueError(
            "RETENTION_EXPORT_S3_BUCKET must be set to use the cold-storage export pipeline."
        )

    # --- Idempotency check ---------------------------------------------------
    existing_key = repo.get_cold_storage_export_key(claim_id)
    if existing_key:
        _log.info(
            "claim_id=%s already exported; skipping (key=%s)", claim_id, existing_key
        )
        return existing_key

    # --- Fetch claim + audit data --------------------------------------------
    claim_data = repo.get_claim(claim_id)
    if claim_data is None:
        raise ValueError(f"Cannot export: claim {claim_id} not found")
    audit_rows, _ = repo.get_claim_history(claim_id)

    manifest = build_claim_manifest(claim_data, audit_rows)
    manifest_bytes = json.dumps(manifest, indent=2, default=str).encode("utf-8")

    # --- Build S3 key --------------------------------------------------------
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in claim_id)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"{config.s3_prefix.rstrip('/')}/{safe_id}/{ts}_manifest.json"

    # --- Upload to S3 --------------------------------------------------------
    put_kwargs: dict[str, Any] = {
        "Bucket": config.s3_bucket,
        "Key": key,
        "Body": manifest_bytes,
        "ContentType": "application/json",
        "StorageClass": config.s3_storage_class,
    }
    if config.encryption == "aws:kms":
        put_kwargs["ServerSideEncryption"] = "aws:kms"
        if config.kms_key_id:
            put_kwargs["SSEKMSKeyId"] = config.kms_key_id
    else:
        put_kwargs["ServerSideEncryption"] = "AES256"

    try:
        import boto3
        from botocore.config import Config as BotocoreConfig

        s3 = boto3.client(
            "s3",
            endpoint_url=config.s3_endpoint,
            config=BotocoreConfig(signature_version="s3v4"),
        )
        s3.put_object(**put_kwargs)
    except Exception as exc:
        raise RuntimeError(
            f"S3 upload failed for claim {claim_id} (bucket={config.s3_bucket}, key={key}): {exc}"
        ) from exc

    _log.info(
        "claim_id=%s exported to s3://%s/%s (storage_class=%s)",
        claim_id,
        config.s3_bucket,
        key,
        config.s3_storage_class,
    )

    # --- Persist export record -----------------------------------------------
    repo.mark_claim_exported(claim_id, export_key=key, actor_id=actor_id)

    return key
