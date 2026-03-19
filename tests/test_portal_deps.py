"""Unit tests for api/portal_deps."""

from unittest.mock import MagicMock

from claim_agent.api.portal_deps import PortalSession, _extract_portal_headers


def _mock_request(
    token: str | None = None,
    cid: str | None = None,
    policy_number: str | None = None,
    vin: str | None = None,
    email: str | None = None,
):
    req = MagicMock()
    headers = {}
    if token is not None:
        headers["x-claim-access-token"] = token
    if cid is not None:
        headers["x-claim-id"] = cid
    if policy_number is not None:
        headers["x-policy-number"] = policy_number
    if vin is not None:
        headers["x-vin"] = vin
    if email is not None:
        headers["x-email"] = email
    req.headers.get = lambda k, default=None: headers.get(k.lower(), default)
    return req


class TestPortalSession:
    def test_dataclass_fields(self):
        session = PortalSession(
            claim_ids=["CLM-001"],
            token="t",
            policy_number="POL-001",
            vin="VIN123",
            email="a@b.com",
        )
        assert session.claim_ids == ["CLM-001"]
        assert session.token == "t"
        assert session.policy_number == "POL-001"
        assert session.vin == "VIN123"
        assert session.email == "a@b.com"


class TestExtractPortalHeaders:
    def test_extracts_all_headers(self):
        req = _mock_request(
            token="tok",
            cid="CLM-001",
            policy_number="POL-001",
            vin="VIN123",
            email="a@b.com",
        )
        t, c, pn, v, e = _extract_portal_headers(req)
        assert t == "tok"
        assert c == "CLM-001"
        assert pn == "POL-001"
        assert v == "VIN123"
        assert e == "a@b.com"

    def test_strips_whitespace(self):
        req = _mock_request(token="  tok  ", policy_number=" POL ")
        t, _, pn, _, _ = _extract_portal_headers(req)
        assert t == "tok"
        assert pn == "POL"

    def test_returns_none_for_missing(self):
        req = _mock_request()
        t, c, pn, v, e = _extract_portal_headers(req)
        assert t is None
        assert c is None
        assert pn is None
        assert v is None
        assert e is None


# require_portal_session and require_claimant_access are tested via
# test_portal_api.py (API-level tests with TestClient)
