import secrets
import uuid
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User, UserStatus
from app.services import SessionService


def get_session_service() -> SessionService:
    return SessionService(get_settings())


def get_current_user(
    studio_session: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
    sessions: SessionService = Depends(get_session_service),
) -> User:
    if not studio_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    user_id = sessions.read(studio_session)
    user = db.scalar(select(User).where(User.id == user_id)) if user_id else None
    if not user or user.status != UserStatus.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or inactive session")
    return user


def require_csrf(
    studio_csrf: Annotated[str | None, Cookie()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> None:
    if not studio_csrf or not x_csrf_token or not secrets.compare_digest(studio_csrf, x_csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token required")


CurrentUser = Annotated[User, Depends(get_current_user)]
CSRF = Annotated[None, Depends(require_csrf)]
