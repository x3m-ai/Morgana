"""
Morgana - User-based auth dependency (JWT Bearer tokens).

Separate from core/auth.py which handles legacy API key auth.

Two auth paths supported on every endpoint:
  1. Bearer JWT  (issued by /api/v2/auth/login or OAuth callback)
  2. KEY header  (legacy API key -> maps to break glass admin for backward compat)

Usage in routers:
    from core.auth_user import get_current_user, require_contributor, require_admin

    @router.get("/...")
    def endpoint(user: User = Depends(get_current_user)):
        ...
"""

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.user import User, BREAK_GLASS_EMAIL

log = logging.getLogger("morgana.auth_user")

_JWT_ALGO = "HS256"


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def make_user_jwt(user: "User") -> str:
    """Issue a signed JWT for the given user."""
    from datetime import datetime, timedelta
    payload = {
        "sub":   user.id,
        "email": user.email,
        "role":  user.role,
        "exp":   datetime.utcnow() + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_JWT_ALGO)


def decode_user_jwt(token: str) -> dict:
    """Decode and validate a user JWT. Raises HTTP 401 on failure."""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[_JWT_ALGO])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def get_current_user(
    authorization: Optional[str] = Header(None),
    key: Optional[str]           = Header(None, alias="KEY"),
    db: Session                  = Depends(get_db),
) -> User:
    """
    Resolve the authenticated user.

    Priority:
      1. Authorization: Bearer <jwt>  -- preferred, issued by auth endpoints
      2. KEY: <api_key>               -- legacy, treated as break glass admin
    """
    # --- Path 1: Bearer JWT ---
    if authorization and authorization.startswith("Bearer "):
        token  = authorization[7:]
        claims = decode_user_jwt(token)
        uid    = claims.get("sub")

        u = db.query(User).filter(User.id == uid).first()
        if not u:
            raise HTTPException(status_code=401, detail="User not found")
        if not u.is_enabled:
            raise HTTPException(status_code=403, detail="Account disabled")
        return u

    # --- Path 2: Legacy KEY header (backward compat) ---
    if key:
        # Validate the key the same way core/auth.py does
        if key == settings.api_key:
            u = db.query(User).filter(User.email == BREAK_GLASS_EMAIL).first()
            if u:
                return u
            # Break glass not yet seeded (first boot race) - accept and let it pass
            raise HTTPException(status_code=503, detail="Break glass not seeded yet - restart server")

        # Also check DB-stored API keys
        import hashlib
        from models.api_key import ApiKey
        khash = hashlib.sha256(key.encode()).hexdigest()
        db_key = db.query(ApiKey).filter(ApiKey.key_hash == khash).first()
        if db_key:
            u = db.query(User).filter(User.email == BREAK_GLASS_EMAIL).first()
            if u:
                return u

    raise HTTPException(status_code=401, detail="Authentication required")


def get_current_user_optional(
    authorization: Optional[str] = Header(None),
    key: Optional[str]           = Header(None, alias="KEY"),
    db: Session                  = Depends(get_db),
) -> Optional[User]:
    """Like get_current_user but returns None instead of raising 401."""
    try:
        return get_current_user(authorization=authorization, key=key, db=db)
    except HTTPException:
        return None


def require_contributor(user: User = Depends(get_current_user)) -> User:
    """Require at least contributor role (admin or contributor), deny reader."""
    if user.role == "reader":
        raise HTTPException(status_code=403, detail="Read-only access: Contributor or Admin required")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Require admin role."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
