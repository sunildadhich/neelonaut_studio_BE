from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, engine, get_db
from app.dependencies import CSRF, CurrentUser, get_session_service
from app.models import (
    ArtifactType, Bookmark, Comment, ContentReport, Document, DocumentStatus,
    DocumentVersion, Follow, Publication, Reaction, User, UserSetting, UserStatus,
    Visibility, Workspace, WorkspaceMember, Profile, utcnow,
)
from app.schemas import (
    AIRequest, CommentCreate, DocumentCreate, DocumentResponse, DocumentUpdate,
    DocumentVersionResponse,
    CommentResponse, LoginRequest, PublicationCreate, PublicationResponse, ReportCreate, ReportResponse, SignupRequest,
    UserResponse, WorkspaceCreate, WorkspaceResponse,
)
from app.services import (
    LocalAIProvider, SessionService, can_access_workspace, can_edit_document,
    hash_password, save_document_version, unique_slug, verify_password,
)

settings = get_settings()
app = FastAPI(title="Neelonaut Studio API", version="1.0.0", docs_url="/docs", redoc_url="/redoc")
app.add_middleware(
    CORSMiddleware, allow_origins=settings.origins, allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


def set_auth_cookies(response: Response, sessions: SessionService, user_id: uuid.UUID) -> None:
    response.set_cookie("studio_session", sessions.issue(user_id), httponly=True, secure=settings.cookie_secure, samesite="lax", max_age=settings.session_ttl_seconds)
    response.set_cookie("studio_csrf", secrets.token_urlsafe(32), httponly=False, secure=settings.cookie_secure, samesite="lax", max_age=settings.session_ttl_seconds)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/auth/signup", response_model=UserResponse, status_code=201)
def signup(payload: SignupRequest, response: Response, db: Session = Depends(get_db), sessions: SessionService = Depends(get_session_service)) -> User:
    user = User(email=payload.email.lower(), username=payload.username, password_hash=hash_password(payload.password), status=UserStatus.active, email_verified_at=utcnow())
    user.profile = Profile(display_name=payload.username)
    db.add(user)
    db.flush()
    db.add(UserSetting(user_id=user.id, settings={}))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "email or username already exists")
    db.refresh(user)
    set_auth_cookies(response, sessions, user.id)
    return user


@app.post("/api/v1/auth/login", response_model=UserResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db), sessions: SessionService = Depends(get_session_service)) -> User:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "invalid credentials")
    if user.status != UserStatus.active:
        raise HTTPException(403, "account is not active")
    set_auth_cookies(response, sessions, user.id)
    return user


@app.post("/api/v1/auth/logout", status_code=204)
def logout(response: Response, _: CSRF, user: CurrentUser) -> None:
    response.delete_cookie("studio_session")
    response.delete_cookie("studio_csrf")


@app.get("/api/v1/auth/me", response_model=UserResponse)
def me(user: CurrentUser) -> User:
    return user


@app.post("/api/v1/workspaces", response_model=WorkspaceResponse, status_code=201)
def create_workspace(payload: WorkspaceCreate, user: CurrentUser, db: Session = Depends(get_db)) -> Workspace:
    workspace = Workspace(owner_id=user.id, name=payload.name)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(workspace)
    return workspace


@app.get("/api/v1/workspaces", response_model=list[WorkspaceResponse])
def list_workspaces(user: CurrentUser, db: Session = Depends(get_db)) -> list[Workspace]:
    return list(db.scalars(select(Workspace).join(WorkspaceMember).where(WorkspaceMember.user_id == user.id).order_by(Workspace.created_at.desc())))


@app.post("/api/v1/documents", response_model=DocumentResponse, status_code=201)
def create_document(payload: DocumentCreate, user: CurrentUser, db: Session = Depends(get_db)) -> Document:
    if not can_access_workspace(db, user.id, payload.workspace_id):
        raise HTTPException(403, "workspace access denied")
    document = Document(workspace_id=payload.workspace_id, owner_id=user.id, title=payload.title, artifact_type=payload.artifact_type, content=payload.content.model_dump())
    db.add(document)
    db.flush()
    save_document_version(db, document, user.id)
    db.commit()
    db.refresh(document)
    return document


@app.get("/api/v1/documents", response_model=list[DocumentResponse])
def list_documents(user: CurrentUser, workspace_id: uuid.UUID | None = None, status_filter: DocumentStatus | None = Query(None, alias="status"), artifact_type: ArtifactType | None = None, db: Session = Depends(get_db)) -> list[Document]:
    query = select(Document).join(WorkspaceMember, WorkspaceMember.workspace_id == Document.workspace_id).where(WorkspaceMember.user_id == user.id)
    if workspace_id:
        query = query.where(Document.workspace_id == workspace_id)
    if status_filter:
        query = query.where(Document.status == status_filter)
    if artifact_type:
        query = query.where(Document.artifact_type == artifact_type)
    return list(db.scalars(query.order_by(Document.updated_at.desc())))


@app.get("/api/v1/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)) -> Document:
    document = db.get(Document, document_id)
    if not document or not can_edit_document(db, user.id, document):
        raise HTTPException(404, "document not found")
    return document


@app.patch("/api/v1/documents/{document_id}", response_model=DocumentResponse)
def update_document(document_id: uuid.UUID, payload: DocumentUpdate, _: CSRF, user: CurrentUser, db: Session = Depends(get_db)) -> Document:
    document = db.get(Document, document_id)
    if not document or not can_edit_document(db, user.id, document):
        raise HTTPException(404, "document not found")
    if document.version != payload.expected_version:
        raise HTTPException(409, "document version conflict")
    save_document_version(db, document, user.id)
    if payload.title is not None:
        document.title = payload.title
    if payload.content is not None:
        document.content = payload.content.model_dump()
    if payload.status is not None:
        document.status = payload.status
    document.version += 1
    db.commit()
    db.refresh(document)
    return document


@app.get("/api/v1/documents/{document_id}/versions", response_model=list[DocumentVersionResponse])
def document_versions(document_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)) -> list[DocumentVersion]:
    document = db.get(Document, document_id)
    if not document or not can_edit_document(db, user.id, document):
        raise HTTPException(404, "document not found")
    return list(db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(DocumentVersion.version.desc())))


@app.post("/api/v1/publications", response_model=PublicationResponse, status_code=201)
def publish(payload: PublicationCreate, _: CSRF, user: CurrentUser, db: Session = Depends(get_db)) -> Publication:
    document = db.get(Document, payload.document_id)
    if not document or document.owner_id != user.id:
        raise HTTPException(404, "document not found")
    publication = db.scalar(select(Publication).where(Publication.document_id == document.id))
    if publication:
        publication.content, publication.title = document.content, document.title
        publication.visibility, publication.excerpt, publication.allow_comments = payload.visibility, payload.excerpt, payload.allow_comments
        publication.published_at = utcnow()
    else:
        publication = Publication(document_id=document.id, author_id=user.id, title=document.title, slug=unique_slug(db, document.title, payload.slug), content=document.content, visibility=payload.visibility, excerpt=payload.excerpt, allow_comments=payload.allow_comments, published_at=utcnow())
        db.add(publication)
    db.commit()
    db.refresh(publication)
    return publication


@app.get("/api/v1/publications/{slug}", response_model=PublicationResponse)
def get_publication(slug: str, db: Session = Depends(get_db)) -> Publication:
    publication = db.scalar(select(Publication).where(Publication.slug == slug, Publication.visibility.in_([Visibility.public, Visibility.unlisted])))
    if not publication:
        raise HTTPException(404, "publication not found")
    return publication


@app.get("/api/v1/discovery/latest", response_model=list[PublicationResponse])
def latest_publications(limit: int = Query(20, ge=1, le=100), q: str | None = None, db: Session = Depends(get_db)) -> list[Publication]:
    query = select(Publication).where(Publication.visibility == Visibility.public).order_by(Publication.published_at.desc()).limit(limit)
    if q:
        query = query.where(or_(Publication.title.ilike(f"%{q}%"), Publication.excerpt.ilike(f"%{q}%")))
    return list(db.scalars(query))


@app.post("/api/v1/ai/generate")
def generate_ai(payload: AIRequest, _: CSRF, user: CurrentUser, db: Session = Depends(get_db)) -> dict:
    if payload.writing_mode == "my_voice" and not payload.consent_my_voice:
        raise HTTPException(400, "explicit consent is required for My Voice")
    provider = LocalAIProvider()
    content = provider.generate(payload.task_type, payload.writing_mode, payload.text, payload.selected_text)
    from app.models import AIGeneration
    generation = AIGeneration(user_id=user.id, task_type=payload.task_type, writing_mode=payload.writing_mode, provider=provider.name, model=provider.model)
    db.add(generation)
    db.commit()
    return {"content": content, "task_type": payload.task_type, "writing_mode": payload.writing_mode, "provider": provider.name, "model": provider.model, "usage": {"input_tokens": None, "output_tokens": None}, "warnings": ["Generated text is a suggestion; review claims and citations before publishing."]}


@app.post("/api/v1/publications/{publication_id}/comments", response_model=CommentResponse, status_code=201)
def comment(publication_id: uuid.UUID, payload: CommentCreate, _: CSRF, user: CurrentUser, db: Session = Depends(get_db)) -> Comment:
    publication = db.get(Publication, publication_id)
    if not publication or publication.visibility != Visibility.public or not publication.allow_comments:
        raise HTTPException(404, "publication not found")
    if payload.parent_id:
        parent = db.get(Comment, payload.parent_id)
        if not parent or parent.publication_id != publication_id:
            raise HTTPException(400, "invalid parent comment")
    value = Comment(publication_id=publication_id, author_id=user.id, parent_id=payload.parent_id, body=payload.body)
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


@app.post("/api/v1/publications/{publication_id}/reactions", status_code=204)
def react(publication_id: uuid.UUID, _: CSRF, user: CurrentUser, db: Session = Depends(get_db)) -> None:
    if not db.get(Publication, publication_id):
        raise HTTPException(404, "publication not found")
    db.merge(Reaction(publication_id=publication_id, user_id=user.id))
    db.commit()


@app.delete("/api/v1/publications/{publication_id}/reactions", status_code=204)
def unreact(publication_id: uuid.UUID, _: CSRF, user: CurrentUser, db: Session = Depends(get_db)) -> None:
    value = db.get(Reaction, (publication_id, user.id))
    if value:
        db.delete(value)
        db.commit()


@app.post("/api/v1/users/{user_id}/follow", status_code=204)
def follow(user_id: uuid.UUID, _: CSRF, user: CurrentUser, db: Session = Depends(get_db)) -> None:
    if user_id == user.id or not db.get(User, user_id):
        raise HTTPException(400, "invalid follow target")
    db.merge(Follow(follower_id=user.id, followed_id=user_id))
    db.commit()


@app.delete("/api/v1/users/{user_id}/follow", status_code=204)
def unfollow(user_id: uuid.UUID, _: CSRF, user: CurrentUser, db: Session = Depends(get_db)) -> None:
    value = db.get(Follow, (user.id, user_id))
    if value:
        db.delete(value)
        db.commit()


@app.post("/api/v1/publications/{publication_id}/reports", response_model=ReportResponse, status_code=201)
def report(publication_id: uuid.UUID, payload: ReportCreate, _: CSRF, user: CurrentUser, db: Session = Depends(get_db)) -> ContentReport:
    if not db.get(Publication, publication_id):
        raise HTTPException(404, "publication not found")
    value = ContentReport(reporter_id=user.id, publication_id=publication_id, reason=payload.reason)
    db.add(value)
    db.commit()
    db.refresh(value)
    return value
