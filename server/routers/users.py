"""
Users router - Morgana platform user management.

GET    /api/v2/users                  list users
GET    /api/v2/users/{id}             get user
POST   /api/v2/users                  create user (admin)
PUT    /api/v2/users/{id}             update user
DELETE /api/v2/users/{id}             delete user
POST   /api/v2/users/{id}/enable      enable user
POST   /api/v2/users/{id}/disable     disable user (break glass cannot be disabled)
GET    /api/v2/users/{id}/tags        get user tags
POST   /api/v2/users/{id}/tags        assign tag to user
DELETE /api/v2/users/{id}/tags/{tag_id}  remove tag from user
GET    /api/v2/users/{id}/workspaces  get user workspaces JSON
PUT    /api/v2/users/{id}/workspaces  replace user workspaces list
"""
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
import bcrypt as _bcrypt_lib
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.auth import require_api_key
from database import get_db
from models.tag import TagAssignment, TagDefinition
from models.user import BREAK_GLASS_EMAIL, ROLES, User

log = logging.getLogger("morgana.router.users")
router = APIRouter()


def _hash_pw(plain: str) -> str:
    return _bcrypt_lib.hashpw(plain.encode(), _bcrypt_lib.gensalt(rounds=12)).decode()


# ---------------------------------------------------------------------------
# User list and retrieval
# ---------------------------------------------------------------------------

@router.get("")
def list_users(
    db: Session = Depends(get_db),
    _: str      = Depends(require_api_key),
):
    """List all users. break glass admin (admin@admin.com) is always first."""
    users = db.query(User).order_by(User.name).all()

    # Break glass always on top
    break_glass = [u for u in users if u.is_break_glass]
    rest        = [u for u in users if not u.is_break_glass]
    ordered     = break_glass + rest

    result = []
    for u in ordered:
        d = u.to_dict()
        # Attach user tag list
        tag_rows = db.query(TagAssignment).filter(
            TagAssignment.entity_type == "user",
            TagAssignment.entity_id   == u.id,
        ).all()
        tags = []
        for row in tag_rows:
            td = db.query(TagDefinition).filter(TagDefinition.id == row.tag_id).first()
            if td:
                tags.append({"id": td.id, "label": td.label, "color": td.color})
        d["tags"] = tags
        result.append(d)

    return result


@router.get("/{user_id}")
def get_user(
    user_id: str,
    db:      Session = Depends(get_db),
    _:       str     = Depends(require_api_key),
):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u.to_dict()


# ---------------------------------------------------------------------------
# Create user
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def create_user(
    payload: dict,
    db:      Session = Depends(get_db),
    _:       str     = Depends(require_api_key),
):
    email         = (payload.get("email") or "").strip().lower()
    name          = (payload.get("name") or "").strip()
    aka           = payload.get("aka")
    password      = payload.get("password") or ""
    role          = payload.get("role", "contributor")
    auth_provider = payload.get("auth_provider", "local")

    if not email:
        raise HTTPException(status_code=422, detail="'email' is required")
    if not name:
        raise HTTPException(status_code=422, detail="'name' is required")
    if role not in ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of: {sorted(ROLES)}")
    if auth_provider == "local" and password and len(password) < 8:
        raise HTTPException(status_code=422, detail="password must be >= 8 chars")

    pw_hash = _hash_pw(password) if password else None

    u = User(
        name             = name,
        email            = email,
        aka              = aka,
        password_hash    = pw_hash,
        role             = role,
        auth_provider    = auth_provider,
        provider_user_id = payload.get("provider_user_id"),
        is_enabled       = bool(payload.get("is_enabled", True)),
        workspaces       = json.dumps(payload.get("workspaces", ["__ALL__"])),
    )
    db.add(u)
    try:
        db.commit()
        db.refresh(u)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    log.info("[USERS] Created: %s <%s> role=%s provider=%s", name, email, role, auth_provider)
    return u.to_dict()


# ---------------------------------------------------------------------------
# Update user
# ---------------------------------------------------------------------------

@router.put("/{user_id}")
def update_user(
    user_id: str,
    payload: dict,
    db:      Session = Depends(get_db),
    _:       str     = Depends(require_api_key),
):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    if "name" in payload and payload["name"]:
        u.name = payload["name"].strip()
    if "aka" in payload:
        u.aka = payload["aka"]
    if "role" in payload:
        r = payload["role"]
        if r not in ROLES:
            raise HTTPException(status_code=422, detail=f"role must be one of: {sorted(ROLES)}")
        if u.is_break_glass and r != "admin":
            raise HTTPException(status_code=400, detail="Break glass account role cannot be changed")
        u.role = r
    if "auth_provider" in payload:
        u.auth_provider = payload["auth_provider"]
    if "provider_user_id" in payload:
        u.provider_user_id = payload["provider_user_id"]
    if "workspaces" in payload:
        wss = payload["workspaces"]
        if not isinstance(wss, list):
            raise HTTPException(status_code=422, detail="workspaces must be a list")
        u.workspaces = json.dumps(wss)
    if "password" in payload and payload["password"]:
        if len(payload["password"]) < 8:
            raise HTTPException(status_code=422, detail="password must be >= 8 chars")
        u.password_hash = _hash_pw(payload["password"])

    u.updated_at = datetime.utcnow()
    try:
        db.commit()
        db.refresh(u)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflict")
    return u.to_dict()


# ---------------------------------------------------------------------------
# Enable / Disable
# ---------------------------------------------------------------------------

@router.post("/{user_id}/enable")
def enable_user(
    user_id: str,
    db:      Session = Depends(get_db),
    _:       str     = Depends(require_api_key),
):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.is_enabled = True
    u.updated_at = datetime.utcnow()
    db.commit()
    return {"id": u.id, "is_enabled": True}


@router.post("/{user_id}/disable")
def disable_user(
    user_id: str,
    db:      Session = Depends(get_db),
    _:       str     = Depends(require_api_key),
):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u.is_break_glass:
        raise HTTPException(status_code=400, detail="Break glass account cannot be disabled")
    u.is_enabled = False
    u.updated_at = datetime.utcnow()
    db.commit()
    return {"id": u.id, "is_enabled": False}


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    db:      Session = Depends(get_db),
    _:       str     = Depends(require_api_key),
):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u.is_break_glass:
        raise HTTPException(status_code=400, detail="Break glass account cannot be deleted")
    db.query(TagAssignment).filter(
        TagAssignment.entity_type == "user",
        TagAssignment.entity_id   == user_id,
    ).delete()
    db.delete(u)
    db.commit()


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

@router.get("/{user_id}/tags")
def get_user_tags(
    user_id: str,
    db:      Session = Depends(get_db),
    _:       str     = Depends(require_api_key),
):
    rows = db.query(TagAssignment).filter(
        TagAssignment.entity_type == "user",
        TagAssignment.entity_id   == user_id,
    ).all()
    result = []
    for row in rows:
        td = db.query(TagDefinition).filter(TagDefinition.id == row.tag_id).first()
        if td:
            d = td.to_dict()
            d["assignment_id"]  = row.id
            d["value_override"] = row.value_override
            result.append(d)
    return result


@router.post("/{user_id}/tags", status_code=201)
def assign_user_tag(
    user_id: str,
    payload: dict,
    db:      Session = Depends(get_db),
    _:       str     = Depends(require_api_key),
):
    tag_id = payload.get("tag_id")
    if not tag_id:
        raise HTTPException(status_code=422, detail="'tag_id' is required")
    td = db.query(TagDefinition).filter(TagDefinition.id == tag_id).first()
    if not td:
        raise HTTPException(status_code=404, detail="Tag not found")
    existing = db.query(TagAssignment).filter(
        TagAssignment.tag_id      == tag_id,
        TagAssignment.entity_type == "user",
        TagAssignment.entity_id   == user_id,
    ).first()
    if existing:
        return {"id": existing.id, "duplicate": True}
    asn = TagAssignment(
        tag_id        = tag_id,
        entity_type   = "user",
        entity_id     = user_id,
        value_override= payload.get("value_override"),
    )
    db.add(asn)
    db.commit()
    return {"id": asn.id, "tag": td.to_dict()}


@router.delete("/{user_id}/tags/{tag_id}", status_code=204)
def remove_user_tag(
    user_id: str,
    tag_id:  str,
    db:      Session = Depends(get_db),
    _:       str     = Depends(require_api_key),
):
    row = db.query(TagAssignment).filter(
        TagAssignment.tag_id      == tag_id,
        TagAssignment.entity_type == "user",
        TagAssignment.entity_id   == user_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------

@router.get("/{user_id}/workspaces")
def get_user_workspaces(
    user_id: str,
    db:      Session = Depends(get_db),
    _:       str     = Depends(require_api_key),
):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        wss = json.loads(u.workspaces or '["__ALL__"]')
    except Exception:
        wss = ["__ALL__"]
    return {"user_id": user_id, "workspaces": wss}


@router.put("/{user_id}/workspaces")
def set_user_workspaces(
    user_id: str,
    payload: dict,
    db:      Session = Depends(get_db),
    _:       str     = Depends(require_api_key),
):
    """
    Replace the user's workspace list.
    Pass {"workspaces": ["__ALL__"]} for unrestricted access.
    Pass {"workspaces": ["ws-id-1", "ws-id-2"]} for restricted access.
    """
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    wss = payload.get("workspaces")
    if not isinstance(wss, list):
        raise HTTPException(status_code=422, detail="workspaces must be a list")
    u.workspaces = json.dumps(wss)
    u.updated_at = datetime.utcnow()
    db.commit()
    return {"user_id": user_id, "workspaces": wss}
