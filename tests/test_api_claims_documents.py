"""Tests for document and attachment routes defined in claims_documents.py.

Covers: list_claim_documents (with version_groups), upload_claim_document,
update_claim_document, list_document_requests, create_document_request,
update_document_request.
"""

import io

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB for all claims-documents API tests."""
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """Clear rate limit buckets before each test to avoid 429 in CI."""
    from claim_agent.api.rate_limit import clear_rate_limit_buckets

    clear_rate_limit_buckets()
    yield


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    from claim_agent.api.server import app

    return TestClient(app)


# CLM-TEST001 is a valid open claim used throughout these tests.
_CLAIM_ID = "CLM-TEST001"
_UNKNOWN_CLAIM = "CLM-DOESNOTEXIST"


# -------------------------------------------------------------------
# GET /claims/{claim_id}/documents - list_claim_documents
# -------------------------------------------------------------------


def test_list_documents_empty(client):
    """list_claim_documents returns an empty list for a claim with no documents."""
    resp = client.get(f"/api/v1/claims/{_CLAIM_ID}/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == _CLAIM_ID
    assert data["documents"] == []
    assert data["total"] == 0
    assert "limit" in data
    assert "offset" in data


def test_list_documents_not_found(client):
    """list_claim_documents returns 404 for unknown claim."""
    resp = client.get(f"/api/v1/claims/{_UNKNOWN_CLAIM}/documents")
    assert resp.status_code == 404


def test_list_documents_invalid_group_by(client):
    """list_claim_documents returns 400 for unsupported group_by value."""
    resp = client.get(f"/api/v1/claims/{_CLAIM_ID}/documents?group_by=invalid")
    assert resp.status_code == 400
    assert "group_by" in resp.json()["detail"].lower()


def test_list_documents_with_version_groups(client):
    """list_claim_documents includes version_groups when group_by=storage_key."""
    resp = client.get(f"/api/v1/claims/{_CLAIM_ID}/documents?group_by=storage_key")
    assert resp.status_code == 200
    data = resp.json()
    assert "version_groups" in data
    assert "version_groups_truncated" in data
    assert isinstance(data["version_groups_truncated"], bool)


# -------------------------------------------------------------------
# POST /claims/{claim_id}/documents - upload_claim_document
# -------------------------------------------------------------------


def test_upload_document(client, tmp_path):
    """upload_claim_document stores a PDF and returns document metadata."""
    pdf_content = b"%PDF-1.4 minimal test content"
    resp = client.post(
        f"/api/v1/claims/{_CLAIM_ID}/documents",
        files={"file": ("test_report.pdf", io.BytesIO(pdf_content), "application/pdf")},
        params={"document_type": "police_report"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == _CLAIM_ID
    assert "document_id" in data
    assert data["document"] is not None
    assert data["document"]["document_type"] == "police_report"


def test_upload_document_disallowed_extension(client):
    """upload_claim_document rejects files with disallowed extensions."""
    resp = client.post(
        f"/api/v1/claims/{_CLAIM_ID}/documents",
        files={"file": ("malware.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "not allowed" in resp.json()["detail"].lower()


def test_upload_document_invalid_document_type(client):
    """upload_claim_document rejects unrecognized document_type values."""
    resp = client.post(
        f"/api/v1/claims/{_CLAIM_ID}/documents",
        files={"file": ("doc.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
        params={"document_type": "not_a_real_type"},
    )
    assert resp.status_code == 400
    assert "document_type" in resp.json()["detail"].lower()


def test_upload_document_not_found(client):
    """upload_claim_document returns 404 for unknown claim."""
    resp = client.post(
        f"/api/v1/claims/{_UNKNOWN_CLAIM}/documents",
        files={"file": ("doc.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
    )
    assert resp.status_code == 404


# -------------------------------------------------------------------
# PATCH /claims/{claim_id}/documents/{doc_id} - update_claim_document
# -------------------------------------------------------------------


def _upload_doc(client, claim_id: str = _CLAIM_ID) -> int:
    """Helper: upload a PDF and return the new document_id."""
    resp = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        files={"file": ("test.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
        params={"document_type": "estimate"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["document_id"]


def test_update_document_review_status(client):
    """update_claim_document updates review_status successfully."""
    doc_id = _upload_doc(client)
    resp = client.patch(
        f"/api/v1/claims/{_CLAIM_ID}/documents/{doc_id}",
        json={"review_status": "reviewed"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["document_id"] == doc_id
    assert data["document"]["review_status"] == "reviewed"


def test_update_document_invalid_review_status(client):
    """update_claim_document returns 400 for an invalid review_status."""
    doc_id = _upload_doc(client)
    resp = client.patch(
        f"/api/v1/claims/{_CLAIM_ID}/documents/{doc_id}",
        json={"review_status": "not_a_valid_status"},
    )
    assert resp.status_code == 400
    assert "review_status" in resp.json()["detail"].lower()


def test_update_document_not_found(client):
    """update_claim_document returns 404 for a missing document."""
    resp = client.patch(
        f"/api/v1/claims/{_CLAIM_ID}/documents/999999",
        json={"review_status": "reviewed"},
    )
    assert resp.status_code == 404


# -------------------------------------------------------------------
# GET /claims/{claim_id}/document-requests - list_document_requests
# -------------------------------------------------------------------


def test_list_document_requests_empty(client):
    """list_document_requests returns an empty list for a claim with no requests."""
    resp = client.get(f"/api/v1/claims/{_CLAIM_ID}/document-requests")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == _CLAIM_ID
    assert data["requests"] == []
    assert data["total"] == 0


def test_list_document_requests_not_found(client):
    """list_document_requests returns 404 for unknown claim."""
    resp = client.get(f"/api/v1/claims/{_UNKNOWN_CLAIM}/document-requests")
    assert resp.status_code == 404


# -------------------------------------------------------------------
# POST /claims/{claim_id}/document-requests - create_document_request
# -------------------------------------------------------------------


def test_create_document_request(client):
    """create_document_request creates a new document request and returns it."""
    resp = client.post(
        f"/api/v1/claims/{_CLAIM_ID}/document-requests",
        json={"document_type": "police_report", "requested_from": "claimant"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == _CLAIM_ID
    assert "request_id" in data
    assert data["request"]["document_type"] == "police_report"


def test_create_document_request_invalid_type(client):
    """create_document_request returns 400 for an unrecognized document_type."""
    resp = client.post(
        f"/api/v1/claims/{_CLAIM_ID}/document-requests",
        json={"document_type": "invalid_type"},
    )
    assert resp.status_code == 400
    assert "document_type" in resp.json()["detail"].lower()


def test_create_document_request_not_found(client):
    """create_document_request returns 404 for unknown claim."""
    resp = client.post(
        f"/api/v1/claims/{_UNKNOWN_CLAIM}/document-requests",
        json={"document_type": "estimate"},
    )
    assert resp.status_code == 404


# -------------------------------------------------------------------
# PATCH /claims/{claim_id}/document-requests/{req_id} - update_document_request
# -------------------------------------------------------------------


def _create_request(client, claim_id: str = _CLAIM_ID) -> int:
    """Helper: create a document request and return its request_id."""
    resp = client.post(
        f"/api/v1/claims/{claim_id}/document-requests",
        json={"document_type": "estimate"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["request_id"]


def test_update_document_request_status(client):
    """update_document_request updates the status to received."""
    req_id = _create_request(client)
    resp = client.patch(
        f"/api/v1/claims/{_CLAIM_ID}/document-requests/{req_id}",
        json={"status": "received"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["request_id"] == req_id
    assert data["request"]["status"] == "received"


def test_update_document_request_invalid_status(client):
    """update_document_request returns 400 for an invalid status value."""
    req_id = _create_request(client)
    resp = client.patch(
        f"/api/v1/claims/{_CLAIM_ID}/document-requests/{req_id}",
        json={"status": "not_a_real_status"},
    )
    assert resp.status_code == 400
    assert "status" in resp.json()["detail"].lower()


def test_update_document_request_not_found(client):
    """update_document_request returns 404 for a missing request."""
    resp = client.patch(
        f"/api/v1/claims/{_CLAIM_ID}/document-requests/999999",
        json={"status": "received"},
    )
    assert resp.status_code == 404
