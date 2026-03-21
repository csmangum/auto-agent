"""Tests for DocumentRepository and document management."""

import pytest


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB for document repository tests."""
    yield


class TestDocumentRepository:
    """Unit tests for DocumentRepository."""

    def test_add_document_returns_id(self, seeded_temp_db):
        from claim_agent.db.document_repository import DocumentRepository
        from claim_agent.db.database import get_db_path

        repo = DocumentRepository(db_path=get_db_path())
        doc_id = repo.add_document("CLM-TEST001", "abc123_report.pdf", document_type="estimate")
        assert isinstance(doc_id, int)
        assert doc_id > 0

    def test_add_document_claim_not_found_raises(self, seeded_temp_db):
        from claim_agent.db.document_repository import DocumentRepository
        from claim_agent.db.database import get_db_path
        from claim_agent.exceptions import ClaimNotFoundError

        repo = DocumentRepository(db_path=get_db_path())
        with pytest.raises(ClaimNotFoundError):
            repo.add_document("CLM-DOESNOTEXIST", "key.pdf", document_type="pdf")

    def test_get_document_returns_dict(self, seeded_temp_db):
        from claim_agent.db.document_repository import DocumentRepository
        from claim_agent.db.database import get_db_path

        repo = DocumentRepository(db_path=get_db_path())
        doc_id = repo.add_document("CLM-TEST001", "key.pdf", document_type="pdf")
        doc = repo.get_document(doc_id)
        assert doc is not None
        assert doc["claim_id"] == "CLM-TEST001"
        assert doc["storage_key"] == "key.pdf"
        assert doc["document_type"] == "pdf"
        assert doc["review_status"] == "pending"
        assert doc["privileged"] is False

    def test_get_document_not_found_returns_none(self, seeded_temp_db):
        from claim_agent.db.document_repository import DocumentRepository
        from claim_agent.db.database import get_db_path

        repo = DocumentRepository(db_path=get_db_path())
        assert repo.get_document(99999) is None

    def test_list_documents_with_filters(self, seeded_temp_db):
        from claim_agent.db.document_repository import DocumentRepository
        from claim_agent.db.database import get_db_path

        repo = DocumentRepository(db_path=get_db_path())
        repo.add_document("CLM-TEST001", "a.pdf", document_type="pdf")
        repo.add_document("CLM-TEST001", "b.jpg", document_type="photo")
        repo.add_document("CLM-TEST001", "c.pdf", document_type="pdf")

        docs, total = repo.list_documents("CLM-TEST001", document_type="pdf")
        assert total == 2
        assert all(d["document_type"] == "pdf" for d in docs)

        docs, total = repo.list_documents("CLM-TEST001", review_status="pending")
        assert total == 3

    def test_update_document_review(self, seeded_temp_db):
        from claim_agent.db.document_repository import DocumentRepository
        from claim_agent.db.database import get_db_path
        from claim_agent.models.document import ReviewStatus

        repo = DocumentRepository(db_path=get_db_path())
        doc_id = repo.add_document("CLM-TEST001", "key.pdf", document_type="pdf")
        updated = repo.update_document_review(doc_id, review_status=ReviewStatus.REVIEWED)
        assert updated is not None
        assert updated["review_status"] == "reviewed"

    def test_create_document_request_returns_id(self, seeded_temp_db):
        from claim_agent.db.document_repository import DocumentRepository
        from claim_agent.db.database import get_db_path

        repo = DocumentRepository(db_path=get_db_path())
        req_id = repo.create_document_request("CLM-TEST001", "police_report", requested_from="claimant")
        assert isinstance(req_id, int)
        assert req_id > 0

    def test_find_pending_document_requests_for_type(self, seeded_temp_db):
        from claim_agent.db.document_repository import DocumentRepository
        from claim_agent.db.database import get_db_path

        repo = DocumentRepository(db_path=get_db_path())
        repo.create_document_request("CLM-TEST001", "estimate")
        repo.create_document_request("CLM-TEST001", "police_report")
        pending = repo.find_pending_document_requests_for_type("CLM-TEST001", "estimate")
        assert len(pending) == 1
        assert pending[0]["document_type"] == "estimate"
        assert pending[0]["status"] in ("requested", "partial")

    def test_link_task_to_document_request(self, seeded_temp_db):
        from claim_agent.db.document_repository import DocumentRepository
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.db.database import get_db_path

        claim_repo = ClaimRepository(db_path=get_db_path())
        doc_repo = DocumentRepository(db_path=get_db_path())
        task_id = claim_repo.create_task("CLM-TEST001", "Get estimate", "request_documents")
        req_id = doc_repo.create_document_request("CLM-TEST001", "estimate")
        ok = doc_repo.link_task_to_document_request(task_id, req_id)
        assert ok is True
        task = claim_repo.get_task(task_id)
        assert task["document_request_id"] == req_id


class TestBuildDocumentVersionGroups:
    def test_groups_by_storage_key_and_marks_current(self, seeded_temp_db):
        from claim_agent.db.document_repository import DocumentRepository, build_document_version_groups
        from claim_agent.db.database import get_db_path

        doc_repo = DocumentRepository(db_path=get_db_path())
        doc_repo.add_document("CLM-TEST001", "same/estimate.pdf", document_type="estimate", version=1)
        doc_repo.add_document("CLM-TEST001", "same/estimate.pdf", document_type="estimate", version=2)
        doc_repo.add_document("CLM-TEST001", "other/photo.jpg", document_type="photo", version=1)
        docs, _ = doc_repo.list_documents("CLM-TEST001", limit=50, offset=0)
        groups = build_document_version_groups(docs)
        by_key = {g["storage_key"]: g for g in groups}
        assert by_key["same/estimate.pdf"]["version_count"] == 2
        est_versions = by_key["same/estimate.pdf"]["versions"]
        current = [v for v in est_versions if v.get("is_current_version")]
        assert len(current) == 1
        assert current[0]["version"] == 2
        assert by_key["other/photo.jpg"]["version_count"] == 1
        assert all(v["is_current_version"] for v in by_key["other/photo.jpg"]["versions"])
