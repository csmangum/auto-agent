"""Unit tests for repair authorization webhook dispatch from workflow output."""

import json
import logging
from unittest.mock import patch

import pytest

from claim_agent.notifications.webhook import dispatch_repair_authorized_from_workflow_output


class TestDispatchRepairAuthorizedFromWorkflowOutput:
    """Tests for _dispatch_repair_authorization_webhook."""

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
