"""
Tags router — CRUD for Tag entities + entity tag assignments.
GET    /api/v2/tags              list all tags
POST   /api/v2/tags              create tag
PUT    /api/v2/tags/{id}         update tag
DELETE /api/v2/tags/{id}         delete tag

GET    /api/v2/tags/entity/{type}/{id}   get tags for an entity
POST   /api/v2/tags/entity/{type}/{id}   assign tag to entity   body: {tag_id}
DELETE /api/v2/tags/entity/{type}/{id}/{tag_id}  remove tag from entity
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Optional

from config import settings
from database import get_db
from models.tag import Tag, EntityTag

log = logging.getLogger("morgana.router.tags")
router = APIRouter()

VALID_SCOPES = {"all", "agent", "script", "chain", "test", "campaign"}


def _auth(key: Optional[str] = Header(None, alias="KEY")):
    if key != settings.api_key:
        raise HTTPException(status_code=403, detail="Forbidden")


def _tag_dict(t: Tag, db: Session) -> dict:
    usage = db.query(EntityTag).filter(EntityTag.tag_id == t.id).count()
    return {
        "id": t.id,
        "name": t.name,
        "group_name": t.group_name,
        "description": t.description,
        "scope": t.scope,
        "color": t.color,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "usage_count": usage,
    }


# ─── Tag CRUD ────────────────────────────────────────────────────────────────

@router.get("")
def list_tags(db: Session = Depends(get_db), _=Depends(_auth)):
    tags = db.query(Tag).order_by(Tag.group_name, Tag.name).all()
    return [_tag_dict(t, db) for t in tags]


@router.post("", status_code=201)
def create_tag(payload: dict, db: Session = Depends(get_db), _=Depends(_auth)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="'name' is required")
    scope = payload.get("scope", "all")
    if scope not in VALID_SCOPES:
        raise HTTPException(status_code=422, detail=f"scope must be one of: {', '.join(sorted(VALID_SCOPES))}")

    tag = Tag(
        name=name,
        group_name=(payload.get("group_name") or "general").strip(),
        description=payload.get("description"),
        scope=scope,
        color=payload.get("color", "#667eea"),
    )
    db.add(tag)
    try:
        db.commit()
        db.refresh(tag)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A tag with this name+group already exists")
    log.info("[TAG] Created: %s / %s", tag.group_name, tag.name)
    return _tag_dict(tag, db)


@router.put("/{tag_id}")
def update_tag(tag_id: str, payload: dict, db: Session = Depends(get_db), _=Depends(_auth)):
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    if "name" in payload and payload["name"]:
        tag.name = payload["name"].strip()
    if "group_name" in payload and payload["group_name"]:
        tag.group_name = payload["group_name"].strip()
    if "description" in payload:
        tag.description = payload["description"]
    if "scope" in payload:
        if payload["scope"] not in VALID_SCOPES:
            raise HTTPException(status_code=422, detail=f"Invalid scope")
        tag.scope = payload["scope"]
    if "color" in payload:
        tag.color = payload["color"]

    try:
        db.commit()
        db.refresh(tag)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate name+group")
    return _tag_dict(tag, db)


@router.delete("/{tag_id}", status_code=204)
def delete_tag(tag_id: str, db: Session = Depends(get_db), _=Depends(_auth)):
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    # Cascade: remove all assignments
    db.query(EntityTag).filter(EntityTag.tag_id == tag_id).delete()
    db.delete(tag)
    db.commit()
    log.info("[TAG] Deleted: %s", tag_id)


# ─── Entity tag assignments ──────────────────────────────────────────────────

@router.get("/entity/{entity_type}/{entity_id}")
def get_entity_tags(entity_type: str, entity_id: str, db: Session = Depends(get_db), _=Depends(_auth)):
    rows = db.query(EntityTag).filter(
        EntityTag.entity_type == entity_type,
        EntityTag.entity_id == entity_id,
    ).all()
    tags = []
    for row in rows:
        t = db.query(Tag).filter(Tag.id == row.tag_id).first()
        if t:
            tags.append(_tag_dict(t, db))
    return tags


@router.post("/entity/{entity_type}/{entity_id}", status_code=201)
def assign_tag(entity_type: str, entity_id: str, payload: dict, db: Session = Depends(get_db), _=Depends(_auth)):
    tag_id = payload.get("tag_id")
    if not tag_id:
        raise HTTPException(status_code=422, detail="'tag_id' is required")
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    # Scope check
    if tag.scope != "all" and tag.scope != entity_type:
        raise HTTPException(status_code=422, detail=f"Tag scope '{tag.scope}' cannot be applied to '{entity_type}'")

    existing = db.query(EntityTag).filter(
        EntityTag.entity_type == entity_type,
        EntityTag.entity_id == entity_id,
        EntityTag.tag_id == tag_id,
    ).first()
    if existing:
        return {"id": existing.id, "duplicate": True}

    et = EntityTag(entity_type=entity_type, entity_id=entity_id, tag_id=tag_id)
    db.add(et)
    db.commit()
    log.info("[TAG] Assigned tag %s to %s/%s", tag_id, entity_type, entity_id)
    return {"id": et.id, "tag": _tag_dict(tag, db)}


@router.delete("/entity/{entity_type}/{entity_id}/{tag_id}", status_code=204)
def remove_tag(entity_type: str, entity_id: str, tag_id: str, db: Session = Depends(get_db), _=Depends(_auth)):
    row = db.query(EntityTag).filter(
        EntityTag.entity_type == entity_type,
        EntityTag.entity_id == entity_id,
        EntityTag.tag_id == tag_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(row)
    db.commit()
