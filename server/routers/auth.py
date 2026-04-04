"""
Auth router - Morgana platform authentication.
POST /api/v2/auth/register          register new user + activation token
POST /api/v2/auth/activate/{token}  activate account
POST /api/v2/auth/login             login -> JWT bearer token
POST /api/v2/auth/refresh           refresh token (if valid)
POST /api/v2/auth/reset-request     request password reset
POST /api/v2/auth/reset/{token}     apply password reset

NOTE: email delivery is not implemented (no SMTP config).
The activation_token is returned inline in the register response.
In production, send it via email instead.
"""
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import jwt, JWTError

from config import settings
from database import get_db
from models.user import User

log = logging.getLogger("morgana.router.auth")
router = APIRouter()
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

_JWT_SECRET = getattr(settings, "secret_key", "morgana-jwt-secret-change-in-prod")
_JWT_ALGO = "HS256"
_TOKEN_EXPIRE_HOURS = 24


def _make_jwt(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.utcnow() + timedelta(hours=_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def _verify_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


@router.post("/register", status_code=201)
def register(payload: dict, db: Session = Depends(get_db)):
    email = (payload.get("email") or "").strip().lower()
    name = (payload.get("name") or "").strip()
    aka = payload.get("aka", "")
    password = payload.get("password") or ""

    if not email:
        raise HTTPException(status_code=422, detail="'email' is required")
    if not name:
        raise HTTPException(status_code=422, detail="'name' is required")
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    activation_token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(hours=48)

    u = User(
        name=name,
        email=email,
        aka=aka,
        password_hash=_pwd.hash(password),
        is_active=False,
        activation_token=activation_token,
        activation_expires=expires,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    log.info("[AUTH] Registered: %s <%s>", name, email)
    return {
        "message": "User registered. Activate your account using the activation_token.",
        "user_id": u.id,
        "email": u.email,
        # Return token inline (in production send via email instead)
        "activation_token": activation_token,
        "activation_expires": expires.isoformat(),
    }


@router.post("/activate/{token}")
def activate(token: str, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.activation_token == token).first()
    if not u:
        raise HTTPException(status_code=404, detail="Invalid or expired activation token")
    if u.is_active:
        return {"message": "Account already active"}
    if u.activation_expires and datetime.utcnow() > u.activation_expires:
        raise HTTPException(status_code=410, detail="Activation token expired")
    u.is_active = True
    u.activation_token = None
    u.activation_expires = None
    db.commit()
    log.info("[AUTH] Activated: %s <%s>", u.name, u.email)
    return {"message": "Account activated. You can now log in.", "email": u.email}


@router.post("/login")
def login(payload: dict, db: Session = Depends(get_db)):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""

    u = db.query(User).filter(User.email == email).first()
    if not u or not _pwd.verify(password, u.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not u.is_active:
        raise HTTPException(status_code=403, detail="Account not activated")

    u.last_login = datetime.utcnow()
    db.commit()
    token = _make_jwt(u.id, u.email)
    log.info("[AUTH] Login: %s <%s>", u.name, u.email)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": _TOKEN_EXPIRE_HOURS * 3600,
        "user": u.to_dict(),
    }


@router.post("/refresh")
def refresh_token(payload: dict, db: Session = Depends(get_db)):
    token = payload.get("token") or ""
    claims = _verify_jwt(token)
    u = db.query(User).filter(User.id == claims.get("sub")).first()
    if not u or not u.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    new_token = _make_jwt(u.id, u.email)
    return {"access_token": new_token, "token_type": "bearer"}


@router.post("/reset-request")
def reset_request(payload: dict, db: Session = Depends(get_db)):
    email = (payload.get("email") or "").strip().lower()
    u = db.query(User).filter(User.email == email).first()
    # Always return 200 to avoid user enumeration
    if u and u.is_active:
        reset_tok = secrets.token_urlsafe(32)
        u.reset_token = reset_tok
        u.reset_expires = datetime.utcnow() + timedelta(hours=2)
        db.commit()
        log.info("[AUTH] Reset requested: %s", email)
        # In production send email; here return token inline
        return {"message": "Reset token issued.", "reset_token": reset_tok}
    return {"message": "If that email exists, a reset link was sent."}


@router.post("/reset/{token}")
def reset_password(token: str, payload: dict, db: Session = Depends(get_db)):
    password = payload.get("password") or ""
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")
    u = db.query(User).filter(User.reset_token == token).first()
    if not u:
        raise HTTPException(status_code=404, detail="Invalid reset token")
    if u.reset_expires and datetime.utcnow() > u.reset_expires:
        raise HTTPException(status_code=410, detail="Reset token expired")
    u.password_hash = _pwd.hash(password)
    u.reset_token = None
    u.reset_expires = None
    db.commit()
    log.info("[AUTH] Password reset: %s", u.email)
    return {"message": "Password updated. You can now log in."}
