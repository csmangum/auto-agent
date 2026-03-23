"""Tests for S3/Glacier cold-storage export pipeline (retention-export)."""

import json
import os
import tempfile
from unittest import mock

import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------


def _make_claim(db_path: str, *, policy: str = "POL-EXP-1", loss_state: str = "California"):
    """Create a claim, transition to closed, archive it, and back-date archived_at."""
    from claim_agent.db.constants import STATUS_CLOSED, STATUS_OPEN, STATUS_PROCESSING
    from claim_agent.db.database import get_connection, init_db
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput

    init_db(db_path)
    repo = ClaimRepository(db_path=db_path)
    claim_input = ClaimInput(
        policy_number=policy,
        vin="1HGCM82633A123456",
        vehicle_year=2020,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date="2019-06-01",
        incident_description="Rear-ended at intersection",
        damage_description="Rear bumper damage",
        loss_state=loss_state,
    )
    claim_id = repo.create_claim(claim_input)
    repo.update_claim_status(claim_id, STATUS_PROCESSING, skip_validation=True)
    repo.update_claim_status(claim_id, STATUS_OPEN, skip_validation=True)
    repo.update_claim_status(claim_id, STATUS_CLOSED, payout_amount=1500.0, skip_validation=True)
    repo.archive_claim(claim_id)
    # Back-date archived_at so claim is past the purge horizon
    with get_connection(db_path) as conn:
        conn.execute(
            text("UPDATE claims SET archived_at = datetime('now', '-4 years') WHERE id = :id"),
            {"id": claim_id},
        )
    return repo, claim_id


# ---------------------------------------------------------------------------
# RetentionExportConfig
# ---------------------------------------------------------------------------


class TestRetentionExportConfig:
    """Settings model tests for RetentionExportConfig."""

    def test_defaults(self):
        from claim_agent.config.settings_model import RetentionExportConfig

        cfg = RetentionExportConfig()
        assert cfg.enabled is False
        assert cfg.s3_bucket == ""
        assert cfg.s3_prefix == "retention-exports"
        assert cfg.s3_endpoint is None
        assert cfg.s3_storage_class == "GLACIER_IR"
        assert cfg.encryption == "AES256"
        assert cfg.kms_key_id is None

    def test_enabled_from_env(self):
        from claim_agent.config.settings_model import RetentionExportConfig

        with mock.patch.dict(
            os.environ,
            {
                "RETENTION_EXPORT_ENABLED": "true",
                "RETENTION_EXPORT_S3_BUCKET": "my-bucket",
                "RETENTION_EXPORT_S3_STORAGE_CLASS": "GLACIER",
                "RETENTION_EXPORT_ENCRYPTION": "aws:kms",
                "RETENTION_EXPORT_KMS_KEY_ID": "arn:aws:kms:us-east-1:123:key/abc",
            },
        ):
            cfg = RetentionExportConfig()
            assert cfg.enabled is True
            assert cfg.s3_bucket == "my-bucket"
            assert cfg.s3_storage_class == "GLACIER"
            assert cfg.encryption == "aws:kms"
            assert cfg.kms_key_id == "arn:aws:kms:us-east-1:123:key/abc"

    def test_empty_endpoint_becomes_none(self):
        from claim_agent.config.settings_model import RetentionExportConfig

        with mock.patch.dict(os.environ, {"RETENTION_EXPORT_S3_ENDPOINT": ""}):
            cfg = RetentionExportConfig()
            assert cfg.s3_endpoint is None

    def test_settings_helper(self):
        from claim_agent.config import reload_settings
        from claim_agent.config.settings import get_retention_export_config

        with mock.patch.dict(
            os.environ,
            {"RETENTION_EXPORT_ENABLED": "true", "RETENTION_EXPORT_S3_BUCKET": "bucket-x"},
        ):
            reload_settings()
            cfg = get_retention_export_config()
            assert cfg["enabled"] is True
            assert cfg["s3_bucket"] == "bucket-x"


# ---------------------------------------------------------------------------
# build_claim_manifest
# ---------------------------------------------------------------------------


class TestBuildClaimManifest:
    def test_manifest_shape(self):
        from claim_agent.storage.export import build_claim_manifest

        claim = {"id": "CLM-1", "policy_number": "POL-1", "status": "archived"}
        audit = [{"action": "created", "created_at": "2020-01-01T00:00:00"}]
        manifest = build_claim_manifest(claim, audit)

        assert manifest["schema_version"] == "1.0"
        assert "exported_at" in manifest
        assert manifest["claim"] == claim
        assert manifest["audit_log"] == audit
        assert manifest["audit_log_truncated"] is False

    def test_manifest_truncates_large_audit_log(self):
        from claim_agent.storage.export import AUDIT_LOG_MAX_ROWS, build_claim_manifest

        claim = {"id": "CLM-2"}
        audit = [{"action": f"event_{i}"} for i in range(AUDIT_LOG_MAX_ROWS + 5)]
        manifest = build_claim_manifest(claim, audit)

        assert len(manifest["audit_log"]) == AUDIT_LOG_MAX_ROWS
        assert manifest["audit_log_truncated"] is True

    def test_manifest_is_json_serialisable(self):
        from claim_agent.storage.export import build_claim_manifest

        claim = {"id": "CLM-3", "payout_amount": 5000.0}
        manifest = build_claim_manifest(claim, [])
        assert json.dumps(manifest)  # must not raise


# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------


class TestRepositoryExportHelpers:
    def test_get_cold_storage_export_key_returns_none_when_not_exported(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            repo, claim_id = _make_claim(db_path)
            key = repo.get_cold_storage_export_key(claim_id)
            assert key is None
        finally:
            os.unlink(db_path)

    def test_mark_claim_exported_sets_columns_and_audit(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from claim_agent.db.database import get_connection

            repo, claim_id = _make_claim(db_path)
            repo.mark_claim_exported(claim_id, export_key="retention-exports/CLM/ts_manifest.json")

            with get_connection(db_path) as conn:
                row = conn.execute(
                    text(
                        "SELECT cold_storage_exported_at, cold_storage_export_key "
                        "FROM claims WHERE id = :id"
                    ),
                    {"id": claim_id},
                ).fetchone()
            assert row is not None
            row_dict = dict(row._mapping)
            assert row_dict["cold_storage_export_key"] == "retention-exports/CLM/ts_manifest.json"
            assert row_dict["cold_storage_exported_at"] is not None

            # Audit entry appended
            history, _ = repo.get_claim_history(claim_id)
            actions = [h["action"] for h in history]
            assert "cold_storage_exported" in actions
        finally:
            os.unlink(db_path)

    def test_get_cold_storage_export_key_returns_key_after_mark(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            repo, claim_id = _make_claim(db_path)
            repo.mark_claim_exported(claim_id, export_key="prefix/id/ts_manifest.json")
            key = repo.get_cold_storage_export_key(claim_id)
            assert key == "prefix/id/ts_manifest.json"
        finally:
            os.unlink(db_path)

    def test_mark_claim_exported_raises_for_unknown_claim(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from claim_agent.db.database import init_db
            from claim_agent.db.repository import ClaimRepository
            from claim_agent.exceptions import ClaimNotFoundError

            init_db(db_path)
            repo = ClaimRepository(db_path=db_path)
            with pytest.raises(ClaimNotFoundError):
                repo.mark_claim_exported("NO-SUCH", export_key="k")
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# list_claims_for_export
# ---------------------------------------------------------------------------


class TestListClaimsForExport:
    def test_returns_eligible_claim(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            repo, claim_id = _make_claim(db_path)
            # archived_at was set 4 years ago; purge horizon is 3 years → eligible
            claims = repo.list_claims_for_export(3)
            assert any(c["id"] == claim_id for c in claims)
        finally:
            os.unlink(db_path)

    def test_excludes_already_exported_claim(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            repo, claim_id = _make_claim(db_path)
            repo.mark_claim_exported(claim_id, export_key="some/key")
            claims = repo.list_claims_for_export(3)
            assert not any(c["id"] == claim_id for c in claims)
        finally:
            os.unlink(db_path)

    def test_excludes_claim_not_past_horizon(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            repo, claim_id = _make_claim(db_path)
            # archived 4 years ago; horizon is 10 years → not eligible
            claims = repo.list_claims_for_export(10)
            assert not any(c["id"] == claim_id for c in claims)
        finally:
            os.unlink(db_path)

    def test_excludes_litigation_hold_by_default(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            repo, claim_id = _make_claim(db_path)
            repo.set_litigation_hold(claim_id, True)
            claims_excl = repo.list_claims_for_export(3, exclude_litigation_hold=True)
            assert not any(c["id"] == claim_id for c in claims_excl)
            claims_incl = repo.list_claims_for_export(3, exclude_litigation_hold=False)
            assert any(c["id"] == claim_id for c in claims_incl)
        finally:
            os.unlink(db_path)

    def test_invalid_years_raises(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from claim_agent.db.database import init_db
            from claim_agent.db.repository import ClaimRepository

            init_db(db_path)
            repo = ClaimRepository(db_path=db_path)
            with pytest.raises(ValueError):
                repo.list_claims_for_export(-1)
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# export_claim_to_cold_storage (mocked boto3)
# ---------------------------------------------------------------------------


class TestExportClaimToColdStorage:
    """Unit tests for the export service with a mocked S3 client."""

    def _make_config(self, **overrides):
        from claim_agent.config.settings_model import RetentionExportConfig

        base = {
            "RETENTION_EXPORT_ENABLED": "true",
            "RETENTION_EXPORT_S3_BUCKET": "test-bucket",
            "RETENTION_EXPORT_S3_PREFIX": "exports",
        }
        base.update({k.upper(): v for k, v in overrides.items()})
        with mock.patch.dict(os.environ, base):
            return RetentionExportConfig()

    def test_raises_when_export_disabled(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from claim_agent.config.settings_model import RetentionExportConfig
            from claim_agent.storage.export import export_claim_to_cold_storage

            repo, claim_id = _make_claim(db_path)
            cfg = RetentionExportConfig()  # enabled=False by default
            with pytest.raises(ValueError, match="RETENTION_EXPORT_ENABLED"):
                export_claim_to_cold_storage(claim_id, repo, cfg)
        finally:
            os.unlink(db_path)

    def test_raises_when_bucket_missing(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from claim_agent.storage.export import export_claim_to_cold_storage

            repo, claim_id = _make_claim(db_path)
            with mock.patch.dict(
                os.environ, {"RETENTION_EXPORT_ENABLED": "true", "RETENTION_EXPORT_S3_BUCKET": ""}
            ):
                from claim_agent.config.settings_model import RetentionExportConfig

                cfg = RetentionExportConfig()
            with pytest.raises(ValueError, match="RETENTION_EXPORT_S3_BUCKET"):
                export_claim_to_cold_storage(claim_id, repo, cfg)
        finally:
            os.unlink(db_path)

    def test_upload_called_with_correct_params(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from claim_agent.storage.export import export_claim_to_cold_storage

            repo, claim_id = _make_claim(db_path)
            cfg = self._make_config()

            mock_s3 = mock.MagicMock()
            with mock.patch("claim_agent.storage.export._make_s3_client", return_value=mock_s3):
                key = export_claim_to_cold_storage(claim_id, repo, cfg)

            mock_s3.put_object.assert_called_once()
            call_kwargs = mock_s3.put_object.call_args.kwargs
            assert call_kwargs["Bucket"] == "test-bucket"
            assert call_kwargs["Key"].startswith("exports/")
            assert call_kwargs["Key"].endswith("_manifest.json")
            assert call_kwargs["StorageClass"] == "GLACIER_IR"
            assert call_kwargs["ServerSideEncryption"] == "AES256"
            assert key == call_kwargs["Key"]
        finally:
            os.unlink(db_path)

    def test_kms_encryption_params(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from claim_agent.storage.export import export_claim_to_cold_storage

            repo, claim_id = _make_claim(db_path)
            cfg = self._make_config(
                retention_export_encryption="aws:kms",
                retention_export_kms_key_id="arn:aws:kms:us-east-1:123:key/abc",
            )

            mock_s3 = mock.MagicMock()
            with mock.patch("claim_agent.storage.export._make_s3_client", return_value=mock_s3):
                export_claim_to_cold_storage(claim_id, repo, cfg)

            call_kwargs = mock_s3.put_object.call_args.kwargs
            assert call_kwargs["ServerSideEncryption"] == "aws:kms"
            assert call_kwargs["SSEKMSKeyId"] == "arn:aws:kms:us-east-1:123:key/abc"
        finally:
            os.unlink(db_path)

    def test_idempotent_skips_second_upload(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from claim_agent.storage.export import export_claim_to_cold_storage

            repo, claim_id = _make_claim(db_path)
            cfg = self._make_config()

            mock_s3 = mock.MagicMock()
            with mock.patch("claim_agent.storage.export._make_s3_client", return_value=mock_s3):
                key1 = export_claim_to_cold_storage(claim_id, repo, cfg)
                key2 = export_claim_to_cold_storage(claim_id, repo, cfg)

            assert key1 == key2
            # put_object only called once (second call is skipped by idempotency check)
            assert mock_s3.put_object.call_count == 1
        finally:
            os.unlink(db_path)

    def test_audit_log_includes_exported_event(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from claim_agent.storage.export import export_claim_to_cold_storage

            repo, claim_id = _make_claim(db_path)
            cfg = self._make_config()

            mock_s3 = mock.MagicMock()
            with mock.patch("claim_agent.storage.export._make_s3_client", return_value=mock_s3):
                export_claim_to_cold_storage(claim_id, repo, cfg)

            history, _ = repo.get_claim_history(claim_id)
            actions = [h["action"] for h in history]
            assert "cold_storage_exported" in actions
        finally:
            os.unlink(db_path)

    def test_s3_error_raises_runtime_error(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from claim_agent.storage.export import export_claim_to_cold_storage

            repo, claim_id = _make_claim(db_path)
            cfg = self._make_config()

            mock_s3 = mock.MagicMock()
            mock_s3.put_object.side_effect = Exception("connection refused")
            with mock.patch("claim_agent.storage.export._make_s3_client", return_value=mock_s3):
                with pytest.raises(RuntimeError, match="S3 upload failed"):
                    export_claim_to_cold_storage(claim_id, repo, cfg)

            # cold_storage_exported_at should NOT be set on failure
            key = repo.get_cold_storage_export_key(claim_id)
            assert key is None
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# CLI: retention-export dry-run
# ---------------------------------------------------------------------------


class TestRetentionExportCLI:
    """CLI integration tests for retention-export command."""

    def test_dry_run_no_upload(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from typer.testing import CliRunner

            from claim_agent.main import app

            _make_claim(db_path)

            runner = CliRunner()
            with mock.patch("claim_agent.main.get_db_path", return_value=db_path):
                result = runner.invoke(
                    app,
                    ["retention-export", "--dry-run", "--years", "3"],
                )
            assert result.exit_code == 0, result.output
            output = json.loads(result.output)
            assert output["dry_run"] is True
            assert "claims_to_export" in output
        finally:
            os.unlink(db_path)

    def test_export_disabled_exits_nonzero(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from typer.testing import CliRunner

            from claim_agent.main import app

            _make_claim(db_path)

            runner = CliRunner()
            with mock.patch("claim_agent.main.get_db_path", return_value=db_path):
                with mock.patch.dict(
                    os.environ,
                    {"RETENTION_EXPORT_ENABLED": "false"},
                ):
                    result = runner.invoke(
                        app,
                        ["retention-export", "--years", "3"],
                    )
            assert result.exit_code != 0

        finally:
            os.unlink(db_path)

    def test_export_uploads_and_marks(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from typer.testing import CliRunner

            from claim_agent.config import reload_settings
            from claim_agent.main import app

            _make_claim(db_path)

            runner = CliRunner()
            mock_s3 = mock.MagicMock()
            with mock.patch("claim_agent.storage.export._make_s3_client", return_value=mock_s3):
                with mock.patch("claim_agent.main.get_db_path", return_value=db_path):
                    with mock.patch.dict(
                        os.environ,
                        {
                            "RETENTION_EXPORT_ENABLED": "true",
                            "RETENTION_EXPORT_S3_BUCKET": "test-bucket",
                        },
                    ):
                        reload_settings()
                        result = runner.invoke(
                            app,
                            ["retention-export", "--years", "3"],
                        )

            assert result.exit_code == 0, result.output
            output = json.loads(result.output)
            assert output["exported_count"] >= 1
            assert output["failed_count"] == 0

            # Verify claim was marked exported
            from claim_agent.db.database import get_connection

            with get_connection(db_path) as conn:
                rows = conn.execute(
                    text(
                        "SELECT id, cold_storage_exported_at FROM claims "
                        "WHERE cold_storage_exported_at IS NOT NULL"
                    )
                ).fetchall()
            assert len(rows) >= 1
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# CLI: retention-purge --export-before-purge
# ---------------------------------------------------------------------------


class TestRetentionPurgeExportBeforePurge:
    def test_export_before_purge_exports_then_purges(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from typer.testing import CliRunner

            from claim_agent.config import reload_settings
            from claim_agent.db.database import get_connection
            from claim_agent.main import app

            _make_claim(db_path)

            runner = CliRunner()
            mock_s3 = mock.MagicMock()
            with mock.patch("claim_agent.storage.export._make_s3_client", return_value=mock_s3):
                with mock.patch("claim_agent.main.get_db_path", return_value=db_path):
                    with mock.patch.dict(
                        os.environ,
                        {
                            "RETENTION_EXPORT_ENABLED": "true",
                            "RETENTION_EXPORT_S3_BUCKET": "test-bucket",
                        },
                    ):
                        reload_settings()
                        result = runner.invoke(
                            app,
                            ["retention-purge", "--years", "3", "--export-before-purge"],
                        )

            assert result.exit_code == 0, result.output
            output = json.loads(result.output)
            assert output["exported_count"] >= 1
            assert output["purged_count"] >= 1
            assert output["failed_count"] == 0

            # Claim should be purged
            with get_connection(db_path) as conn:
                row = conn.execute(text("SELECT status FROM claims LIMIT 1")).fetchone()
            assert row is not None
            assert dict(row._mapping)["status"] == "purged"
        finally:
            os.unlink(db_path)

    def test_export_before_purge_requires_enabled(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from typer.testing import CliRunner

            from claim_agent.config import reload_settings
            from claim_agent.main import app

            _make_claim(db_path)

            runner = CliRunner()
            with mock.patch("claim_agent.main.get_db_path", return_value=db_path):
                with mock.patch.dict(
                    os.environ, {"RETENTION_EXPORT_ENABLED": "false"}
                ):
                    reload_settings()
                    result = runner.invoke(
                        app,
                        ["retention-purge", "--years", "3", "--export-before-purge"],
                    )
            assert result.exit_code != 0
        finally:
            os.unlink(db_path)
