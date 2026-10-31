from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from itsdangerous import BadSignature, URLSafeTimedSerializer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Document, DocumentVersion, Publication, User, Workspace, WorkspaceMember

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


class SessionService:
    def __init__(self, settings: Settings):
        self.serializer = URLSafeTimedSerializer(settings.secret_key, salt="studio-session")
        self.max_age = settings.session_ttl_seconds

    def issue(self, user_id: uuid.UUID) -> str:
        return self.serializer.dumps({"sub": str(user_id), "nonce": secrets.token_urlsafe(8)})

    def read(self, token: str) -> uuid.UUID | None:
        try:
            value = self.serializer.loads(token, max_age=self.max_age)
            return uuid.UUID(value["sub"])
        except (BadSignature, KeyError, ValueError):
            return None


def slugify(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result or "publication"


def unique_slug(db: Session, title: str, requested: str | None = None) -> str:
    base = slugify(requested or title)
    candidate, suffix = base, 2
    while db.scalar(select(Publication.id).where(Publication.slug == candidate)):
        candidate, suffix = f"{base}-{suffix}", suffix + 1
    return candidate


def can_access_workspace(db: Session, user_id: uuid.UUID, workspace_id: uuid.UUID) -> bool:
    return db.scalar(select(WorkspaceMember.workspace_id).where(
        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
    )) is not None


def can_edit_document(db: Session, user_id: uuid.UUID, document: Document) -> bool:
    if document.owner_id == user_id:
        return True
    return db.scalar(select(WorkspaceMember.workspace_id).where(
        WorkspaceMember.workspace_id == document.workspace_id,
        WorkspaceMember.user_id == user_id,
        WorkspaceMember.role.in_(["owner", "editor"]),
    )) is not None


def save_document_version(db: Session, document: Document, user_id: uuid.UUID) -> None:
    db.add(DocumentVersion(
        document_id=document.id, version=document.version, title=document.title,
        content=document.content, created_by=user_id
    ))


class AIProvider(Protocol):
    name: str
    model: str

    def generate(self, task_type: str, writing_mode: str, text: str, selected_text: str | None) -> str: ...


@dataclass
class LocalAIProvider:
    name: str = "local"
    model: str = "deterministic-template"

    def generate(self, task_type: str, writing_mode: str, text: str, selected_text: str | None) -> str:
        subject = selected_text or text
        prefix = {"playful": "Here is an engaging take", "scientific": "Structured analysis", "un-serious": "A delightfully odd take", "my_voice": "Suggested draft"}[writing_mode]
        if task_type == "summarize":
            return f"{prefix}: {subject[:500]}"
        if task_type == "title":
            return f"{prefix}: {subject[:80].strip().rstrip('.')}"
        if task_type == "outline":
            return f"{prefix}:\n1. Context\n2. Core ideas\n3. Examples\n4. Limitations\n5. Conclusion"
        return f"{prefix} for the following user-provided material:\n\n{subject}"
