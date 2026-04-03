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


def require_api_key(
    key: Optional[str] = Header(None, alias="KEY"),
    db: Session = Depends(get_db),
) -> str:
    """FastAPI dependency — raise 401 if the KEY header is missing or invalid."""
    if not key:
        raise HTTPException(status_code=401, detail="API key required")

    # 1. Master env-var key (always works even if DB is empty)
    if key == settings.api_key:
        return key

    # 2. DB-stored keys (checked by hash — plaintext never stored)
    from models.api_key import ApiKey
    khash = hash_key(key)
    db_key = db.query(ApiKey).filter(ApiKey.key_hash == khash).first()
    if db_key:
        return key

    raise HTTPException(status_code=401, detail="Invalid API key")
