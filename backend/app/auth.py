import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AuthSession, User

hasher = PasswordHash.recommended()
DUMMY_HASH = hasher.hash("never-a-valid-login-credential")
COOKIE = "prisma_session"


def token_hash(token: str):
    return hashlib.sha256(token.encode()).hexdigest()


def establish(db: Session, user: User, response: Response):
    token = secrets.token_urlsafe(32)
    lifetime = settings().session_days * 86400
    db.add(
        AuthSession(
            token_hash=token_hash(token),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=lifetime),
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE,
        token,
        max_age=lifetime,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="strict",
        path="/",
    )


def current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE, "")
    session = db.get(AuthSession, token_hash(token)) if token else None
    expires = session.expires_at.replace(tzinfo=timezone.utc) if session else None
    if not session or expires <= datetime.now(timezone.utc):
        raise HTTPException(401, "Sign in to continue.")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "Session no longer valid. Sign in again.")
    return user
