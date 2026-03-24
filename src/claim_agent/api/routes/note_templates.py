"""CRUD API for server-driven note templates (adjuster quick-insert snippets)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import require_role
from claim_agent.db.note_template_repository import NoteTemplateRepository

router = APIRouter(prefix="/note-templates", tags=["note-templates"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")
RequireSupervisor = require_role("supervisor", "admin", "executive")
RequireAdmin = require_role("admin")

MAX_LABEL = 120
MAX_BODY = 5000
MAX_CATEGORY = 80


class NoteTemplateCreateBody(BaseModel):
    label: str = Field(..., min_length=1, max_length=MAX_LABEL)
    body: str = Field(..., min_length=1, max_length=MAX_BODY)
    category: Optional[str] = Field(default=None, max_length=MAX_CATEGORY)
    sort_order: int = Field(default=0, ge=0)

    @field_validator("label", "body", mode="after")
    @classmethod
    def strip_and_validate_not_blank(cls, v: str, info) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError(f"{info.field_name} cannot be blank or whitespace-only")
        return stripped

    @field_validator("category", mode="after")
    @classmethod
    def normalize_category(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


class NoteTemplateUpdateBody(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=MAX_LABEL)
    body: Optional[str] = Field(default=None, min_length=1, max_length=MAX_BODY)
    category: Optional[str] = Field(default=None, max_length=MAX_CATEGORY)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = Field(default=None, ge=0)

    @field_validator("label", "body", mode="after")
    @classmethod
    def strip_and_validate_not_blank(cls, v: Optional[str], info) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError(f"{info.field_name} cannot be blank or whitespace-only")
        return stripped

    @field_validator("category", mode="after")
    @classmethod
    def normalize_category(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


@router.get("")
def list_note_templates(
    active_only: bool = False,
    auth: AuthContext = RequireAdjuster,
):
    """List note templates. Adjusters always see active only; others may request all."""
    repo = NoteTemplateRepository()
    filter_active = active_only or auth.role == "adjuster"
    templates = repo.list(active_only=filter_active)
    return {"templates": templates}


@router.post("", status_code=201)
def create_note_template(
    body: NoteTemplateCreateBody,
    auth: AuthContext = RequireSupervisor,
):
    """Create a new note template (supervisor+)."""
    repo = NoteTemplateRepository()
    t = repo.create(
        label=body.label,
        body=body.body,
        category=body.category,
        sort_order=body.sort_order,
        created_by=auth.identity,
    )
    return t


@router.patch("/{template_id}")
def update_note_template(
    template_id: int,
    body: NoteTemplateUpdateBody,
    _auth: AuthContext = RequireSupervisor,
):
    """Update a note template (supervisor+)."""
    repo = NoteTemplateRepository()
    if repo.get(template_id) is None:
        raise HTTPException(status_code=404, detail="Note template not found")

    raw = body.model_dump(exclude_unset=True)
    kwargs: dict = {}
    for field in ("label", "body", "is_active", "sort_order", "category"):
        if field in raw:
            kwargs[field] = raw[field]

    t = repo.update(template_id, **kwargs)
    if t is None:
        raise HTTPException(status_code=404, detail="Note template not found")
    return t


@router.delete("/{template_id}", status_code=204)
def delete_note_template(
    template_id: int,
    _auth: AuthContext = RequireAdmin,
) -> Response:
    """Hard-delete a note template (admin only). Prefer PATCH is_active=false."""
    repo = NoteTemplateRepository()
    if not repo.delete(template_id):
        raise HTTPException(status_code=404, detail="Note template not found")
    return Response(status_code=204)
