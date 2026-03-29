"""
Scripts router — CRUD for Script entities (Atomic Red Team tests + custom scripts).
GET /api/v2/scripts          list with optional filters
GET /api/v2/scripts/{id}     single script detail
POST /api/v2/scripts         create custom script
DELETE /api/v2/scripts/{id}  delete custom script
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from database import get_db
from models.script import Script

router = APIRouter()


@router.get("")
def list_scripts(
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    executor: Optional[str] = Query(None),
    tcode: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(1000, le=5000),
    offset: int = Query(0),
    count_only: bool = Query(False),
):
    q = db.query(Script)
    if search:
        q = q.filter(or_(Script.name.ilike(f"%{search}%"), Script.tcode.ilike(f"%{search}%")))
    if platform:
        q = q.filter(or_(Script.platform == platform, Script.platform == "all"))
    if executor:
        q = q.filter(Script.executor == executor)
    if tcode:
        q = q.filter(Script.tcode == tcode.upper())
    if source:
        q = q.filter(Script.source == source)

    total = q.count()
    if count_only:
        return {"total": total}

    scripts = q.order_by(Script.tcode, Script.name).offset(offset).limit(limit).all()

    return [
        {
            "id": s.id,
            "name": s.name,
            "tcode": s.tcode,
            "tactic": s.tactic,
            "executor": s.executor,
            "platform": s.platform,
            "source": s.source,
            "atomic_id": s.atomic_id,
            "command": s.command,
            "cleanup_command": s.cleanup_command,
            "input_args": s.input_args,
            "description": s.description,
        }
        for s in scripts
    ]


@router.get("/{script_id}")
def get_script(script_id: int, db: Session = Depends(get_db)):
    s = db.query(Script).filter(Script.id == script_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Script not found")
    return {
        "id": s.id,
        "name": s.name,
        "tcode": s.tcode,
        "tactic": s.tactic,
        "executor": s.executor,
        "platform": s.platform,
        "source": s.source,
        "atomic_id": s.atomic_id,
        "command": s.command,
        "cleanup_command": s.cleanup_command,
        "input_args": s.input_args,
        "description": s.description,
    }


@router.post("", status_code=201)
def create_script(payload: dict, db: Session = Depends(get_db)):
    required = ("name", "tcode", "executor", "command")
    for field in required:
        if not payload.get(field):
            raise HTTPException(status_code=422, detail=f"Field '{field}' is required")

    tcode_upper = payload["tcode"].upper()
    source = payload.get("source", "custom")

    # Deduplication: if a script with the same name + tcode + source already exists, return it
    existing = (
        db.query(Script)
        .filter(Script.name == payload["name"], Script.tcode == tcode_upper, Script.source == source)
        .first()
    )
    if existing:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=200, content={"id": existing.id, "name": existing.name, "duplicate": True})

    s = Script(
        name=payload["name"],
        tcode=tcode_upper,
        tactic=payload.get("tactic"),
        executor=payload["executor"],
        command=payload["command"],
        cleanup_command=payload.get("cleanup_command"),
        input_args=payload.get("input_args"),
        platform=payload.get("platform", "all"),
        source=source,
        description=payload.get("description"),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "name": s.name}


@router.delete("/{script_id}", status_code=204)
def delete_script(script_id: int, db: Session = Depends(get_db)):
    s = db.query(Script).filter(Script.id == script_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Script not found")
    if s.source != "custom":
        raise HTTPException(status_code=409, detail="Only custom scripts can be deleted. Atomic scripts are managed via the submodule.")
    db.delete(s)
    db.commit()
