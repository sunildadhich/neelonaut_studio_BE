from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import ArtifactType, DocumentStatus, Visibility


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SignupRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(APIModel):
    id: uuid.UUID
    email: EmailStr
    username: str
    status: str
    email_verified_at: datetime | None


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceResponse(APIModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str


ALLOWED_BLOCKS = {"paragraph", "heading", "quote", "code", "image", "list", "divider"}


class DocumentContent(BaseModel):
    blocks: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("blocks")
    @classmethod
    def validate_blocks(cls, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for block in blocks:
            if block.get("type") not in ALLOWED_BLOCKS:
                raise ValueError(f"unsupported block type: {block.get('type')}")
        return blocks


class DocumentCreate(BaseModel):
    workspace_id: uuid.UUID
    title: str = Field(min_length=1, max_length=300)
    artifact_type: ArtifactType = ArtifactType.article
    content: DocumentContent = Field(default_factory=DocumentContent)


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: DocumentContent | None = None
    status: DocumentStatus | None = None
    expected_version: int = Field(ge=1)


class DocumentResponse(APIModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    artifact_type: ArtifactType
    status: DocumentStatus
    content: dict[str, Any]
    version: int


class DocumentVersionResponse(APIModel):
    id: uuid.UUID
    document_id: uuid.UUID
    version: int
    title: str
    content: dict[str, Any]
    created_by: uuid.UUID
    created_at: datetime


class PublicationCreate(BaseModel):
    document_id: uuid.UUID
    visibility: Visibility = Visibility.public
    excerpt: str | None = Field(default=None, max_length=1000)
    slug: str | None = Field(default=None, max_length=320)
    allow_comments: bool = True


class PublicationResponse(APIModel):
    id: uuid.UUID
    document_id: uuid.UUID
    author_id: uuid.UUID
    title: str
    slug: str
    excerpt: str | None
    content: dict[str, Any]
    visibility: Visibility
    published_at: datetime | None


class AIRequest(BaseModel):
    task_type: Literal["outline", "draft", "rewrite", "clarify", "shorten", "expand", "summarize", "title", "explain", "examples", "research"]
    writing_mode: Literal["playful", "scientific", "un-serious", "my_voice"] = "scientific"
    text: str = Field(min_length=1, max_length=20000)
    selected_text: str | None = Field(default=None, max_length=10000)
    consent_my_voice: bool = False


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    parent_id: uuid.UUID | None = None


class CommentResponse(APIModel):
    id: uuid.UUID
    publication_id: uuid.UUID
    author_id: uuid.UUID
    parent_id: uuid.UUID | None
    body: str
    created_at: datetime


class ReportCreate(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ReportResponse(APIModel):
    id: uuid.UUID
    reporter_id: uuid.UUID
    publication_id: uuid.UUID | None
    comment_id: uuid.UUID | None
    reason: str
    status: str
    created_at: datetime
