"""
Morgana - Auth router.

Endpoints
---------
POST /api/v2/auth/login                 Local (break glass) email + password login
POST /api/v2/auth/logout                Clear client-side JWT hint
POST /api/v2/auth/refresh               Re-issue JWT from a valid existing token
GET  /api/v2/auth/me                    Current user info
POST /api/v2/auth/change-password       Change break glass password

GET  /api/v2/auth/oauth/{provider}      Start OAuth2 authorization-code flow
GET  /api/v2/auth/oauth/{provider}/callback   OAuth2 callback (redirects to UI)

GET  /api/v2/auth/providers             List configured OAuth providers

Legacy (kept for backward compat)
POST /api/v2/auth/register              Create user (admin, no activation email)
POST /api/v2/auth/activate/{token}      Activate token flow
POST /api/v2/auth/reset-request         Request password reset
POST /api/v2/auth/reset/{token}         Apply password reset
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
import bcrypt as _bcrypt_lib
from sqlalchemy.orm import Session

from config import settings
from core.auth_user import get_current_user, make_user_jwt
from core.oauth import (
    VALID_PROVIDERS,
    build_state,
    configured_providers,
    get_provider,
    verify_state,
)
from database import get_db
from models.user import BREAK_GLASS_EMAIL, User

log = logging.getLogger("morgana.router.auth")
router = APIRouter()

_DEFAULT_PW = "admin"


def _hash_pw(plain: str) -> str:
    return _bcrypt_lib.hashpw(plain.encode(), _bcrypt_lib.gensalt(rounds=12)).decode()


def _verify_pw(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt_lib.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_public_url(request: Request) -> str:
    if settings.oauth_public_url:
        return settings.oauth_public_url.rstrip("/")
    host = request.url.hostname
    port = settings.port
    return f"https://{host}:{port}"


def _break_glass_has_default_password(u: User) -> bool:
    if not u.is_break_glass:
        return False
    try:
        return _verify_pw(_DEFAULT_PW, u.password_hash or "")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Local (break glass) login
# ---------------------------------------------------------------------------

@router.post("/login")
def login(payload: dict, db: Session = Depends(get_db)):
    """Authenticate with email + password (local accounts only)."""
    email    = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""

    if not email or not password:
        raise HTTPException(status_code=422, detail="Email and password required")

    u = db.query(User).filter(User.email == email).first()
    if not u:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if u.auth_provider != "local":
        raise HTTPException(
            status_code=400,
            detail=f"This account uses {u.auth_provider} login. Use the SSO button."
        )
    if not u.password_hash or not _verify_pw(password, u.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not u.is_enabled:
        raise HTTPException(status_code=403, detail="Account disabled")

    u.last_login = datetime.utcnow()
    u.updated_at = datetime.utcnow()
    db.commit()

    token = make_user_jwt(u)
    log.info("[AUTH] Local login: %s <%s>", u.name, u.email)

    resp = u.to_dict()
    resp["default_password_warning"] = _break_glass_has_default_password(u)
    return {
        "access_token": token,
        "token_type":   "bearer",
        "expires_in":   settings.jwt_expire_hours * 3600,
        "user":         resp,
    }


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------

@router.post("/change-password")
def change_password(
    payload: dict,
    db:      Session = Depends(get_db),
    user:    User    = Depends(get_current_user),
):
    """Change the password of a local account (admin or self)."""
    if user.auth_provider != "local":
        raise HTTPException(status_code=400, detail="Cannot change password for OAuth accounts")

    new_pw     = payload.get("new_password") or ""
    current_pw = payload.get("current_password") or ""

    if len(new_pw) < 12:
        raise HTTPException(status_code=422, detail="Password must be at least 12 characters")

    if user.is_break_glass:
        if not current_pw:
            raise HTTPException(status_code=422, detail="current_password required")
        if not _verify_pw(current_pw, user.password_hash or ""):
            raise HTTPException(status_code=401, detail="Current password incorrect")

    target_email = (payload.get("email") or user.email).lower()
    target = db.query(User).filter(User.email == target_email).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.auth_provider != "local":
        raise HTTPException(status_code=400, detail="Target is not a local account")

    target.password_hash = _hash_pw(new_pw)
    target.updated_at    = datetime.utcnow()
    db.commit()
    log.info("[AUTH] Password changed for: %s", target.email)
    return {
        "message":                  "Password updated",
        "default_password_warning": _break_glass_has_default_password(target),
    }


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

@router.post("/refresh")
def refresh_token(payload: dict, db: Session = Depends(get_db)):
    """Exchange a valid JWT for a fresh one."""
    from core.auth_user import decode_user_jwt
    token  = payload.get("token") or ""
    claims = decode_user_jwt(token)
    uid    = claims.get("sub")
    u = db.query(User).filter(User.id == uid).first()
    if not u or not u.is_enabled:
        raise HTTPException(status_code=401, detail="User not found or disabled")
    return {"access_token": make_user_jwt(u), "token_type": "bearer"}


@router.post("/logout")
def logout():
    return {"message": "Logged out - clear your local token"}


@router.get("/me")
def whoami(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    resp = user.to_dict()
    resp["default_password_warning"] = _break_glass_has_default_password(user)
    return resp


@router.get("/providers")
def list_providers():
    return {"local": True, "providers": configured_providers()}


# ---------------------------------------------------------------------------
# OAuth2 authorization-code flow
# ---------------------------------------------------------------------------

@router.get("/oauth/{provider}")
async def oauth_start(
    provider:  str,
    request:   Request,
    return_to: str = Query(default="/ui/"),
):
    """Start OAuth2 flow - redirect browser to provider."""
    if provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    p = get_provider(provider)
    if not p.is_configured():
        raise HTTPException(
            status_code=501,
            detail=f"Provider '{provider}' is not configured. Set the required env vars."
        )

    base         = _infer_public_url(request)
    redirect_uri = f"{base}/api/v2/auth/oauth/{provider}/callback"
    state        = build_state(provider, return_to)

    if provider == "oidc":
        auth_url = await p._auth_url_async(redirect_uri, state)
    else:
        auth_url = p.auth_url(redirect_uri, state)

    log.info("[AUTH] OAuth start: provider=%s", provider)
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    request:  Request,
    code:     Optional[str] = Query(default=None),
    state:    Optional[str] = Query(default=None),
    error:    Optional[str] = Query(default=None),
    db:       Session       = Depends(get_db),
):
    """OAuth2 callback: exchange code -> userinfo -> internal lookup -> issue JWT."""
    ui_base = _infer_public_url(request)

    def _fail(msg: str):
        return RedirectResponse(
            url=f"{ui_base}/ui/login.html?error={quote(msg)}",
            status_code=302,
        )

    if error:
        return _fail(f"Provider error: {error}")
    if not code or not state:
        return _fail("Missing code or state")

    try:
        state_data = verify_state(state)
    except ValueError as e:
        return _fail(str(e))

    if state_data.get("p") != provider:
        return _fail("State mismatch")

    p = get_provider(provider)
    redirect_uri = f"{ui_base}/api/v2/auth/oauth/{provider}/callback"
    try:
        info = await p.exchange(code, redirect_uri)
    except Exception as exc:
        log.error("[AUTH] OAuth exchange failed: %s %s", provider, exc)
        return _fail(f"Login failed: {exc}")

    email = (info.get("email") or "").lower()
    sub   = info.get("sub", "")

    if not email:
        return _fail("Provider returned no email")

    u = db.query(User).filter(User.email == email).first()
    if not u:
        log.warning("[AUTH] OAuth rejected (not registered): %s via %s", email, provider)
        return _fail(f"Access denied: {email} is not registered in Morgana")
    if not u.is_enabled:
        return _fail("Account disabled")

    # Update provider info
    if u.provider_user_id != sub:
        u.provider_user_id = sub
    u.last_login = datetime.utcnow()
    u.updated_at = datetime.utcnow()
    db.commit()

    token     = make_user_jwt(u)
    return_to = state_data.get("r", "/ui/")
    log.info("[AUTH] OAuth login OK: %s <%s> via %s", u.name, u.email, provider)

    # Pass token in URL fragment (not query string - fragment is never sent to server)
    return RedirectResponse(url=f"{ui_base}{return_to}#token={token}", status_code=302)


# ---------------------------------------------------------------------------
# Legacy endpoints (backward compatibility)
# ---------------------------------------------------------------------------

@router.post("/register", status_code=201)
def register(payload: dict, db: Session = Depends(get_db)):
    email    = (payload.get("email") or "").strip().lower()
    name     = (payload.get("name") or "").strip()
    password = payload.get("password") or ""

    if not email or not name:
        raise HTTPException(status_code=422, detail="email and name required")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    u = User(
        name          = name,
        email         = email,
        aka           = payload.get("aka"),
        password_hash = _hash_pw(password) if password else None,
        role          = payload.get("role", "contributor"),
        auth_provider = payload.get("auth_provider", "local"),
        is_enabled    = True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    log.info("[AUTH] Created user: %s <%s>", name, email)
    return u.to_dict()


@router.post("/activate/{token}")
def activate(token: str, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.activation_token == token).first()
    if not u:
        raise HTTPException(status_code=404, detail="Invalid activation token")
    u.is_enabled         = True
    u.activation_token   = None
    u.activation_expires = None
    db.commit()
    return {"message": "Account activated", "email": u.email}


@router.post("/reset-request")
def reset_request(payload: dict, db: Session = Depends(get_db)):
    email = (payload.get("email") or "").strip().lower()
    u     = db.query(User).filter(User.email == email).first()
    if u and u.is_enabled and u.auth_provider == "local":
        reset_tok       = secrets.token_urlsafe(32)
        u.reset_token   = reset_tok
        u.reset_expires = datetime.utcnow() + timedelta(hours=2)
        db.commit()
        return {"message": "Reset token issued.", "reset_token": reset_tok}
    return {"message": "If that email exists, a reset link was sent."}


@router.post("/reset/{token}")
def reset_password(token: str, payload: dict, db: Session = Depends(get_db)):
    password = payload.get("password") or ""
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    u = db.query(User).filter(User.reset_token == token).first()
    if not u:
        raise HTTPException(status_code=404, detail="Invalid reset token")
    if u.reset_expires and datetime.utcnow() > u.reset_expires:
        raise HTTPException(status_code=410, detail="Reset token expired")
    u.password_hash = _hash_pw(password)
    u.reset_token   = None
    u.reset_expires = None
    u.updated_at    = datetime.utcnow()
    db.commit()
    return {"message": "Password updated"}
