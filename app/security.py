
import hashlib
import os
import secrets
import time

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, UserSession

password_hash = PasswordHash.recommended()
SESSION_COOKIE = "tp_connect_session"
SESSION_LIFETIME = 8 * 60 * 60


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Password must contain 12–128 characters.")
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return password_hash.verify(password, stored_hash)
    except (ValueError, TypeError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user_id: int | None = None):
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)

    session = UserSession(
        token_hash=token_digest(raw_token),
        user_id=user_id,
        csrf_token=csrf_token,
        expires_at=int(time.time()) + SESSION_LIFETIME,
    )
    db.add(session)
    db.commit()
    return raw_token, session


def find_session(db: Session, raw_token: str | None):
    if not raw_token or len(raw_token) > 200:
        return None

    session = db.scalar(
        select(UserSession).where(
            UserSession.token_hash == token_digest(raw_token)
        )
    )

    if session is None:
        return None

    if session.expires_at <= int(time.time()):
        db.delete(session)
        db.commit()
        return None

    return session


def cookie_options():
    return {
        "key": SESSION_COOKIE,
        "httponly": True,
        "secure": os.getenv("COOKIE_SECURE", "false").lower() == "true",
        "samesite": "lax",
        "path": "/",
        "max_age": SESSION_LIFETIME,
    }
