"""
Morgana - API Keys CRUD router

Endpoints (all require valid KEY header):
  GET    /api/v2/api-keys          -> list all keys (masked)
  POST   /api/v2/api-keys          -> create new key (returns plaintext once)
  DELETE /api/v2/api-keys/{key_id} -> revoke a key

Key format  : mrg_<64 hex chars>  (secrets.token_hex(32) prefixed with mrg_)
Stored      : SHA-256 hash only — plaintext never persisted
Displayed   : key_prefix (first 12 chars) + "..."
"""

import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.auth import hash_key, require_api_key
from database import get_db
from models.api_key import ApiKey

router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ApiKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: str


class ApiKeyCreated(BaseModel):
    id: str
    name: str
    key: str          # full plaintext — shown ONCE, never stored
    key_prefix: str
    created_at: str


class CreateKeyBody(BaseModel):
    name: str


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _gen_key() -> str:
    """Generate a new API key: mrg_ + 64 hex chars."""
    return "mrg_" + secrets.token_hex(32)


def _fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ApiKeyOut])
def list_api_keys(
    _key: str = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Return all keys with prefix only (plaintext never returned after creation)."""
    rows = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return [
        ApiKeyOut(
            id=r.id,
            name=r.name,
            key_prefix=r.key_prefix,
            created_at=_fmt_dt(r.created_at),
        )
        for r in rows
    ]


@router.post("", response_model=ApiKeyCreated, status_code=201)
def create_api_key(
    body: CreateKeyBody,
    _key: str = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Create a new API key. The full plaintext is returned exactly once."""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    plaintext = _gen_key()
    khash     = hash_key(plaintext)
    prefix    = plaintext[:12]          # "mrg_xxxxxxxx"
    key_id    = str(uuid.uuid4())
    now       = datetime.now(timezone.utc)

    db.add(ApiKey(
        id=key_id,
        name=name,
        key_hash=khash,
        key_prefix=prefix,
        created_at=now,
    ))
    db.commit()

    return ApiKeyCreated(
        id=key_id,
        name=name,
        key=plaintext,
        key_prefix=prefix,
        created_at=_fmt_dt(now),
    )


@router.delete("/{key_id}", status_code=204)
def delete_api_key(
    key_id: str,
    _key: str = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Revoke (delete) a stored API key by its ID."""
    row = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="API key not found")
    db.delete(row)
    db.commit()
