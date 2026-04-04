"""
Users router - Morgana platform user management.
GET    /api/v2/users              list users
GET    /api/v2/users/{id}         get user
POST   /api/v2/users              create user (admin)
PUT    /api/v2/users/{id}         update user
DELETE /api/v2/users/{id}         delete user
GET    /api/v2/users/{id}/tags    get user tags
POST   /api/v2/users/{id}/tags    assign tag to user
DELETE /api/v2/users/{id}/tags/{tag_id}  remove tag
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from passlib.context import CryptContext

from config import settings
from database import get_db
from models.user import User
from models.tag import TagDefinition, TagAssignment

log = logging.getLogger("morgana.router.users")
router = APIRouter()
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _auth(key: Optional[str] = Header(None, alias="KEY")):
    if key != settings.api_key:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("")
def list_users(db: Session = Depends(get_db), _=Depends(_auth)):
    users = db.query(User).order_by(User.name).all()
    return [u.to_dict() for u in users]


@router.get("/{user_id}")
def get_user(user_id: str, db: Session = Depends(get_db), _=Depends(_auth)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u.to_dict()


@router.post("", status_code=201)
def create_user(payload: dict, db: Session = Depends(get_db), _=Depends(_auth)):
    email = (payload.get("email") or "").strip().lower()
    name = (payload.get("name") or "").strip()
    password = payload.get("password") or ""
    if not email:
        raise HTTPException(status_code=422, detail="'email' is required")
    if not name:
        raise HTTPException(status_code=422, detail="'name' is required")
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")

    u = User(
        name=name,
        email=email,
        aka=payload.get("aka"),
        password_hash=_pwd.hash(password),
        is_active=bool(payload.get("is_active", True)),
        is_admin=bool(payload.get("is_admin", False)),
    )
    db.add(u)
    try:
        db.commit()
        db.refresh(u)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    log.info("[USER] Created: %s <%s>", name, email)
    return u.to_dict()


@router.put("/{user_id}")
def update_user(user_id: str, payload: dict, db: Session = Depends(get_db), _=Depends(_auth)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if "name" in payload and payload["name"]:
        u.name = payload["name"].strip()
    if "aka" in payload:
        u.aka = payload["aka"]
    if "is_active" in payload:
        u.is_active = bool(payload["is_active"])
    if "is_admin" in payload:
        u.is_admin = bool(payload["is_admin"])
    if "password" in payload and payload["password"]:
        if len(payload["password"]) < 8:
            raise HTTPException(status_code=422, detail="password must be >= 8 chars")
        u.password_hash = _pwd.hash(payload["password"])
    try:
        db.commit()
        db.refresh(u)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflict")
    return u.to_dict()


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: str, db: Session = Depends(get_db), _=Depends(_auth)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    db.query(TagAssignment).filter(
        TagAssignment.entity_type == "user",
        TagAssignment.entity_id == user_id,
    ).delete()
    db.delete(u)
    db.commit()


@router.get("/{user_id}/tags")
def get_user_tags(user_id: str, db: Session = Depends(get_db), _=Depends(_auth)):
    rows = db.query(TagAssignment).filter(
        TagAssignment.entity_type == "user",
        TagAssignment.entity_id == user_id,
    ).all()
    result = []
    for row in rows:
        td = db.query(TagDefinition).filter(TagDefinition.id == row.tag_id).first()
        if td:
            d = td.to_dict()
            d["assignment_id"] = row.id
            d["value_override"] = row.value_override
            result.append(d)
    return result


@router.post("/{user_id}/tags", status_code=201)
def assign_user_tag(user_id: str, payload: dict, db: Session = Depends(get_db), _=Depends(_auth)):
    tag_id = payload.get("tag_id")
    if not tag_id:
        raise HTTPException(status_code=422, detail="'tag_id' is required")
    td = db.query(TagDefinition).filter(TagDefinition.id == tag_id).first()
    if not td:
        raise HTTPException(status_code=404, detail="Tag not found")
    existing = db.query(TagAssignment).filter(
        TagAssignment.tag_id == tag_id,
        TagAssignment.entity_type == "user",
        TagAssignment.entity_id == user_id,
    ).first()
    if existing:
        return {"id": existing.id, "duplicate": True}
    asn = TagAssignment(tag_id=tag_id, entity_type="user", entity_id=user_id,
                        value_override=payload.get("value_override"))
    db.add(asn)
    db.commit()
    return {"id": asn.id, "tag": td.to_dict()}


@router.delete("/{user_id}/tags/{tag_id}", status_code=204)
def remove_user_tag(user_id: str, tag_id: str, db: Session = Depends(get_db), _=Depends(_auth)):
    row = db.query(TagAssignment).filter(
        TagAssignment.tag_id == tag_id,
        TagAssignment.entity_type == "user",
        TagAssignment.entity_id == user_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(row)
    db.commit()
