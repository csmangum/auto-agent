"""Tests for NoteTemplateRepository and note-templates API."""

import pytest
from fastapi.testclient import TestClient

from claim_agent.config import reload_settings
from claim_agent.db.note_template_repository import NoteTemplateRepository
from claim_agent.api.server import app


# --- Repository tests ---


@pytest.fixture
def repo(temp_db):
    reload_settings()
    return NoteTemplateRepository()


def test_create_and_get(repo):
    t = repo.create("Initial Contact", "Contacted claimant.", category="general")
    assert t["label"] == "Initial Contact"
    assert t["body"] == "Contacted claimant."
    assert t["category"] == "general"
    assert t["is_active"] in (1, True)
    fetched = repo.get(t["id"])
    assert fetched is not None
    assert fetched["label"] == "Initial Contact"


def test_list_all(repo):
    repo.create("A", "Body A", sort_order=1)
    repo.create("B", "Body B", sort_order=0)
    all_templates = repo.list()
    assert len(all_templates) == 2
    assert all_templates[0]["label"] == "B"


def test_list_active_only(repo):
    t1 = repo.create("Active", "Active body")
    t2 = repo.create("Inactive", "Inactive body")
    repo.update(t2["id"], is_active=False)

    active = repo.list(active_only=True)
    assert len(active) == 1
    assert active[0]["id"] == t1["id"]

    all_templates = repo.list(active_only=False)
    assert len(all_templates) == 2


def test_update_fields(repo):
    t = repo.create("Old", "Old body", category="cat1", sort_order=0)
    updated = repo.update(t["id"], label="New", body="New body", category="cat2", sort_order=5)
    assert updated is not None
    assert updated["label"] == "New"
    assert updated["body"] == "New body"
    assert updated["category"] == "cat2"
    assert updated["sort_order"] == 5


def test_update_category_to_none(repo):
    t = repo.create("X", "body", category="something")
    updated = repo.update(t["id"], category=None)
    assert updated is not None
    assert updated["category"] is None


def test_update_nonexistent(repo):
    result = repo.update(99999, label="nope")
    assert result is None


def test_delete(repo):
    t = repo.create("Del", "Delete me")
    assert repo.delete(t["id"])
    assert repo.get(t["id"]) is None


def test_delete_nonexistent(repo):
    assert not repo.delete(99999)


# --- API route tests ---


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    reload_settings()
    return TestClient(app)


def test_api_list_empty(client):
    r = client.get("/api/note-templates")
    assert r.status_code == 200
    assert r.json()["templates"] == []


def test_api_create_and_list(client):
    r = client.post(
        "/api/note-templates",
        json={"label": "Test", "body": "Test body", "sort_order": 0},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["label"] == "Test"
    assert data["body"] == "Test body"

    r2 = client.get("/api/note-templates")
    assert r2.status_code == 200
    assert len(r2.json()["templates"]) == 1


def test_api_update(client):
    r = client.post(
        "/api/note-templates",
        json={"label": "Before", "body": "Before body"},
    )
    tid = r.json()["id"]

    r2 = client.patch(f"/api/note-templates/{tid}", json={"label": "After"})
    assert r2.status_code == 200
    assert r2.json()["label"] == "After"


def test_api_update_not_found(client):
    r = client.patch("/api/note-templates/99999", json={"label": "X"})
    assert r.status_code == 404


def test_api_delete(client):
    r = client.post(
        "/api/note-templates",
        json={"label": "D", "body": "D body"},
    )
    tid = r.json()["id"]

    r2 = client.delete(f"/api/note-templates/{tid}")
    assert r2.status_code == 204

    r3 = client.get("/api/note-templates")
    assert len(r3.json()["templates"]) == 0


def test_api_delete_not_found(client):
    r = client.delete("/api/note-templates/99999")
    assert r.status_code == 404


def test_api_deactivate_hides_from_adjuster(temp_db, monkeypatch):
    """Inactive templates should be excluded when adjuster role requests list."""
    # Use a supervisor key to create/modify templates, and an adjuster key to fetch.
    monkeypatch.setenv("API_KEYS", "sk-sup:supervisor:supervisor1,sk-adj:adjuster:adjuster1")
    reload_settings()
    client_auth = TestClient(app)

    r = client_auth.post(
        "/api/note-templates",
        json={"label": "T1", "body": "body1"},
        headers={"X-API-Key": "sk-sup"},
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    client_auth.patch(
        f"/api/note-templates/{tid}",
        json={"is_active": False},
        headers={"X-API-Key": "sk-sup"},
    )

    client_auth.post(
        "/api/note-templates",
        json={"label": "T2", "body": "body2"},
        headers={"X-API-Key": "sk-sup"},
    )

    # Adjuster should only see the active template
    r3 = client_auth.get("/api/note-templates", headers={"X-API-Key": "sk-adj"})
    assert r3.status_code == 200
    templates = r3.json()["templates"]
    assert len(templates) == 1
    assert templates[0]["label"] == "T2"


def test_api_create_validation(client):
    r = client.post("/api/note-templates", json={"label": "", "body": "body"})
    assert r.status_code == 422

    r2 = client.post("/api/note-templates", json={"label": "L", "body": ""})
    assert r2.status_code == 422


def test_api_create_whitespace_only_rejected(client):
    """Whitespace-only label or body should be rejected with 422."""
    r = client.post("/api/note-templates", json={"label": "   ", "body": "body"})
    assert r.status_code == 422

    r2 = client.post("/api/note-templates", json={"label": "Label", "body": "   "})
    assert r2.status_code == 422


def test_api_create_category_normalized(client):
    """Empty-string category should be stored as None."""
    r = client.post(
        "/api/note-templates",
        json={"label": "L", "body": "Body", "category": "  "},
    )
    assert r.status_code == 201
    assert r.json()["category"] is None


def test_repo_create_blank_label_raises(repo):
    """Repository should raise ValueError for whitespace-only label."""
    with pytest.raises(ValueError, match="label"):
        repo.create("   ", "some body")


def test_repo_create_blank_body_raises(repo):
    """Repository should raise ValueError for whitespace-only body."""
    with pytest.raises(ValueError, match="body"):
        repo.create("A label", "   ")


def test_repo_update_blank_label_raises(repo):
    """Repository should raise ValueError when updating label to whitespace-only."""
    t = repo.create("Original", "Original body")
    with pytest.raises(ValueError, match="label"):
        repo.update(t["id"], label="   ")


def test_repo_update_blank_body_raises(repo):
    """Repository should raise ValueError when updating body to whitespace-only."""
    t = repo.create("Original", "Original body")
    with pytest.raises(ValueError, match="body"):
        repo.update(t["id"], body="   ")
