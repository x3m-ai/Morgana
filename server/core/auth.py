"""
Morgana - Shared authentication dependency

Accepts requests that present either:
  1. The master key from MORGANA_API_KEY env var (settings.api_key), OR
  2. Any active key stored in the api_keys table (matched by SHA-256 hash)

Usage in routers:
    from core.auth import require_api_key
    @router.get("/...")
    def endpoint(key: str = Depends(require_api_key), db: Session = Depends(get_db)):
        ...
"""

import hashlib
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from config import settings
from database import get_db


def hash_key(key: str) -> str:
    """Return the SHA-256 hex digest of a key string."""
    return hashlib.sha256(key.encode()).hexdigest()


def verify_key_value(key: str, db: Session) -> bool:
    """Return True if *key* is valid (master key or active DB-stored key).

    Used by endpoints that receive the key as a query parameter rather than
    a header (e.g. WebSocket and console endpoints where custom headers are
    not practical).
    """
    if not key:
        return False
    if key == settings.api_key:
        return True
    from models.api_key import ApiKey
    khash = hash_key(key)
    return db.query(ApiKey).filter(ApiKey.key_hash == khash).first() is not None


def require_api_key(
    key: Optional[str] = Header(None, alias="KEY"),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> str:
    """
    FastAPI dependency - raise 401 if no valid auth is provided.
    Accepts:
      1. Authorization: Bearer <JWT>  (browser UI / JWT session)
      2. KEY: <master_key>            (Merlino add-in / direct API)
      3. KEY: <db_api_key>            (named DB-stored API keys)
    """
    # 1. JWT Bearer token (browser UI)
    if authorization and authorization.startswith("Bearer "):
        from jose import JWTError, jwt as _jwt
        try:
            _jwt.decode(authorization[7:], settings.secret_key, algorithms=["HS256"])
            return "__jwt__"
        except JWTError:
            pass  # fall through to KEY check

    if not key:
        raise HTTPException(status_code=401, detail="API key required")

    # 2. Master key (always works even if DB is empty)
    if key == settings.api_key:
        return key

    # 3. DB-stored keys (checked by hash - plaintext never stored)
    from models.api_key import ApiKey
    khash = hash_key(key)
    db_key = db.query(ApiKey).filter(ApiKey.key_hash == khash).first()
    if db_key:
        return key

    raise HTTPException(status_code=401, detail="Invalid API key")
