"""Unit tests for repair authorization webhook dispatch from workflow output."""

import json
import logging
from unittest.mock import patch

from claim_agent.notifications.webhook import dispatch_repair_authorized_from_workflow_output


class TestDispatchRepairAuthorizedFromWorkflowOutput:
    """Tests for dispatch_repair_authorized_from_workflow_output."""

    def test_dispatches_when_full_payload_present(self):
        """Webhook is called with correct payload when workflow output has all fields."""
        output = json.dumps({
            "authorization_id": "RA-ABCD1234",
            "claim_id": "CLM-001",
            "shop_id": "SHOP-001",
            "shop_name": "Premier Auto",
            "shop_phone": "555-0100",
            "authorized_amount": 3500.0,
            "shop_webhook_url": "https://shop.example.com/hook",
        })
        log = logging.getLogger("test")
        with patch("claim_agent.notifications.webhook.dispatch_repair_authorized") as mock:
            dispatch_repair_authorized_from_workflow_output(output, log=log)
            mock.assert_called_once()
            call_kw = mock.call_args[1]
            assert call_kw["claim_id"] == "CLM-001"
            assert call_kw["shop_id"] == "SHOP-001"
            assert call_kw["shop_name"] == "Premier Auto"
            assert call_kw["shop_phone"] == "555-0100"
            assert call_kw["authorized_amount"] == 3500.0
            assert call_kw["authorization_id"] == "RA-ABCD1234"
            assert call_kw["shop_webhook_url"] == "https://shop.example.com/hook"

    def test_dispatches_with_minimal_payload(self):
        """Webhook is called when only authorization_id present (uses defaults for rest)."""
        output = json.dumps({"authorization_id": "RA-MINIMAL"})
        log = logging.getLogger("test")
        with patch("claim_agent.notifications.webhook.dispatch_repair_authorized") as mock:
            dispatch_repair_authorized_from_workflow_output(output, log=log)
            mock.assert_called_once()
            call_kw = mock.call_args[1]
            assert call_kw["authorization_id"] == "RA-MINIMAL"
            assert call_kw["claim_id"] == ""
            assert call_kw["shop_id"] == ""
            assert call_kw["authorized_amount"] == 0.0

    def test_skips_when_no_authorization_id(self):
        """Webhook is not called when authorization_id is missing."""
        output = json.dumps({"payout_amount": 2100.0, "claim_id": "CLM-001"})
        log = logging.getLogger("test")
        with patch("claim_agent.notifications.webhook.dispatch_repair_authorized") as mock:
            dispatch_repair_authorized_from_workflow_output(output, log=log)
            mock.assert_not_called()

    def test_skips_when_invalid_json(self):
        """Webhook is not called when workflow output is invalid JSON."""
        log = logging.getLogger("test")
        with patch("claim_agent.notifications.webhook.dispatch_repair_authorized") as mock:
            dispatch_repair_authorized_from_workflow_output("not valid json", log=log)
            mock.assert_not_called()

    def test_skips_when_output_is_not_dict(self):
        """Webhook is not called when parsed output is not a dict."""
        output = json.dumps(["list", "not", "dict"])
        log = logging.getLogger("test")
        with patch("claim_agent.notifications.webhook.dispatch_repair_authorized") as mock:
            dispatch_repair_authorized_from_workflow_output(output, log=log)
            mock.assert_not_called()

    def test_handles_null_fields_from_pydantic(self):
        """Webhook uses empty string / 0 when optional fields are null."""
        output = json.dumps({
            "authorization_id": "RA-X",
            "claim_id": None,
            "shop_id": None,
            "shop_name": None,
            "shop_phone": None,
            "authorized_amount": None,
        })
        log = logging.getLogger("test")
        with patch("claim_agent.notifications.webhook.dispatch_repair_authorized") as mock:
            dispatch_repair_authorized_from_workflow_output(output, log=log)
            mock.assert_called_once()
            call_kw = mock.call_args[1]
            assert call_kw["claim_id"] == ""
            assert call_kw["shop_id"] == ""
            assert call_kw["authorized_amount"] == 0.0


class TestParseReopenedOutput:
    """Unit tests for _parse_reopened_output covering all three code paths."""

    def _make_result_with_pydantic(self, target_claim_type: str):
        """Build a mock crew result with a Pydantic ReopenedWorkflowOutput as the last task output."""
        from unittest.mock import MagicMock
        from claim_agent.models.workflow_output import ReopenedWorkflowOutput

        pydantic_output = ReopenedWorkflowOutput(
            target_claim_type=target_claim_type,
            reopening_reason_validated=True,
        )
        task_out = MagicMock()
        task_out.output = pydantic_output
        result = MagicMock()
        result.tasks_output = [task_out]
        return result

    def _make_result_with_raw_json(self, raw: str):
        """Build a mock crew result with a raw JSON string (no Pydantic output)."""
        from unittest.mock import MagicMock

        task_out = MagicMock()
        task_out.output = "plain text"  # not a ReopenedWorkflowOutput
        result = MagicMock()
        result.tasks_output = [task_out]
        result.raw = raw
        return result

    def _make_result_empty(self):
        """Build a mock crew result with no usable output."""
        from unittest.mock import MagicMock

        result = MagicMock()
        result.tasks_output = []
        result.raw = "no useful data here"
        return result

    # --- Pydantic path ---

    def test_pydantic_partial_loss(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_pydantic("partial_loss")
        assert _parse_reopened_output(result) == ClaimType.PARTIAL_LOSS.value

    def test_pydantic_total_loss(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_pydantic("total_loss")
        assert _parse_reopened_output(result) == ClaimType.TOTAL_LOSS.value

    def test_pydantic_bodily_injury(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_pydantic("bodily_injury")
        assert _parse_reopened_output(result) == ClaimType.BODILY_INJURY.value

    def test_pydantic_reopened_circular_defaults_to_partial_loss(self):
        """Pydantic path: circular reopened value must default to partial_loss."""
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_pydantic("reopened")
        assert _parse_reopened_output(result) == ClaimType.PARTIAL_LOSS.value

    # --- Regex fallback path ---

    def test_regex_partial_loss(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_raw_json('{"target_claim_type": "partial_loss", "other": 1}')
        assert _parse_reopened_output(result) == ClaimType.PARTIAL_LOSS.value

    def test_regex_total_loss(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_raw_json('{"target_claim_type": "total_loss"}')
        assert _parse_reopened_output(result) == ClaimType.TOTAL_LOSS.value

    def test_regex_bodily_injury(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_raw_json('{"target_claim_type": "bodily_injury"}')
        assert _parse_reopened_output(result) == ClaimType.BODILY_INJURY.value

    def test_regex_reopened_circular_defaults_to_partial_loss(self):
        """Regex fallback: circular 'reopened' must not be returned; default to partial_loss."""
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_raw_json('{"target_claim_type": "reopened"}')
        assert _parse_reopened_output(result) == ClaimType.PARTIAL_LOSS.value

    # --- Default path ---

    def test_default_when_no_usable_output(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_empty()
        assert _parse_reopened_output(result) == ClaimType.PARTIAL_LOSS.value
