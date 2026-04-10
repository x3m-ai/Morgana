"""
Scripts router — CRUD for Script entities (Atomic Red Team tests + custom scripts).
GET    /api/v2/scripts          list with optional filters
GET    /api/v2/scripts/{id}     single script detail
POST   /api/v2/scripts          create custom script
PUT    /api/v2/scripts/{id}     update script (custom only for source field, all editable)
DELETE /api/v2/scripts/{id}     delete custom script
POST   /api/v2/scripts/{id}/execute   run script on a specific agent
"""
import hashlib
import hmac
import logging
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from sqlalchemy import or_

from config import settings
from core.auth import require_api_key
from database import get_db
from models.script import Script
from models.agent import Agent
from models.test import Test
from models.job import Job
from core.job_queue import job_queue

log = logging.getLogger("morgana.router.scripts")
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
    # Exclude internal system records from user-visible list
    q = q.filter(Script.source != "system")
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
            "target_agent_paw": s.target_agent_paw or None,
        }
        for s in scripts
    ]


@router.get("/{script_id}")
def get_script(script_id: str, db: Session = Depends(get_db)):
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
        "target_agent_paw": s.target_agent_paw or None,
    }


@router.post("", status_code=201)
def create_script(payload: dict, db: Session = Depends(get_db)):
    required = ("name", "tcode", "executor", "command")
    for field in required:
        if not payload.get(field):
            raise HTTPException(status_code=422, detail=f"Field '{field}' is required")

    tcode_upper = payload["tcode"].upper()
    source = payload.get("source", "morgana")

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
def delete_script(script_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    from models.job import Job
    from models.test import Test
    from models.chain import ChainStep
    s = db.query(Script).filter(Script.id == script_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Script not found")
    # Remove FK dependents first
    db.query(Job).filter(Job.script_id == script_id).delete(synchronize_session=False)
    db.query(Test).filter(Test.script_id == script_id).delete(synchronize_session=False)
    db.query(ChainStep).filter(ChainStep.script_id == script_id).delete(synchronize_session=False)
    db.delete(s)
    db.commit()
    log.info("[SCRIPT] Deleted: %s (%s)", s.name, script_id)


@router.put("/{script_id}")
def update_script(script_id: str, payload: dict, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    s = db.query(Script).filter(Script.id == script_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Script not found")

    editable = ("name", "tcode", "tactic", "executor", "platform", "command",
                "cleanup_command", "input_args", "description", "download_url",
                "target_agent_paw")
    for field in editable:
        if field in payload:
            val = payload[field]
            if field == "tcode" and val:
                val = val.upper()
            setattr(s, field, val)

    s.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(s)
    log.info("[SCRIPT] Updated: %s (%s)", s.name, script_id)
    return {
        "id": s.id, "name": s.name, "tcode": s.tcode, "tactic": s.tactic,
        "executor": s.executor, "platform": s.platform, "source": s.source,
        "command": s.command, "cleanup_command": s.cleanup_command,
        "input_args": s.input_args, "description": s.description,
        "target_agent_paw": s.target_agent_paw or None,
    }


@router.post("/{script_id}/execute", status_code=201)
def execute_script(script_id: str, payload: dict, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    """Run a script on a specific agent immediately (creates Test + Job + enqueues)."""
    s = db.query(Script).filter(Script.id == script_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Script not found")

    paw = payload.get("paw")
    if not paw:
        raise HTTPException(status_code=422, detail="'paw' (agent PAW) is required")

    agent = db.query(Agent).filter(Agent.paw == paw).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{paw}' not found")

    if agent.status == "offline":
        raise HTTPException(status_code=409, detail=f"Agent '{paw}' is offline")

    # Resolve input_args: use defaults + caller overrides
    input_overrides = payload.get("input_args", {})

    # Create Test record
    test = Test(
        id=str(uuid.uuid4()),
        script_id=script_id,
        script_name=s.name,
        tcode=s.tcode,
        agent_id=agent.id,
        operation_name=f"manual:{s.name}",
        state="pending",
    )
    db.add(test)
    db.flush()  # get test.id

    # Create Job record
    job_id = str(uuid.uuid4())
    import json as _json
    job = Job(
        id=job_id,
        test_id=test.id,
        agent_id=agent.id,
        script_id=script_id,
        executor=s.executor,
        command=s.command,
        cleanup_command=s.cleanup_command,
        input_args=_json.dumps(input_overrides) if input_overrides else s.input_args,
        timeout_seconds=payload.get("timeout_seconds", 300),
        status="pending",
    )
    # Signature is empty (dev mode) - agent accepts unsigned jobs.
    # Production: sign with agent-specific token stored server-side.
    job.signature = ""

    db.add(job)
    db.commit()

    # Enqueue for agent pickup
    job_queue.enqueue(paw, job_id)
    log.info("[EXECUTE] Script %s queued for agent %s (job=%s, test=%s)", script_id, paw, job_id, test.id)

    return {"test_id": test.id, "job_id": job_id, "paw": paw, "queued": True}


@router.post("/execute-adhoc", status_code=201)
def execute_adhoc(payload: dict, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    """Execute a command on an agent immediately without saving a Script first.

    Body: {"command": "...", "cleanup_command": "", "executor": "powershell|cmd|bash", "paw": "..."}
    Returns: {"job_id", "paw", "queued": true}
    """
    command = (payload.get("command") or "").strip()
    cleanup = (payload.get("cleanup_command") or "").strip()
    executor = payload.get("executor") or "powershell"
    paw = payload.get("paw") or ""

    if not command:
        raise HTTPException(status_code=422, detail="'command' is required")
    if not paw:
        raise HTTPException(status_code=422, detail="'paw' is required")

    agent = db.query(Agent).filter(Agent.paw == paw).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{paw}' not found")
    if agent.status == "offline":
        raise HTTPException(status_code=409, detail=f"Agent '{paw}' is offline")

    # Create a transient Test with no script link
    test = Test(
        id=str(uuid.uuid4()),
        script_id=None,
        tcode="adhoc",
        agent_id=agent.id,
        operation_name="adhoc",
        state="pending",
    )
    db.add(test)
    db.flush()

    # Job: script_id uses sentinel "_adhoc" because the DB column is NOT NULL.
    # FK constraint is not enforced (PRAGMA foreign_keys = 0).
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        test_id=test.id,
        agent_id=agent.id,
        script_id="_adhoc",
        executor=executor,
        command=command,
        cleanup_command=cleanup or None,
        timeout_seconds=payload.get("timeout_seconds", 300),
        status="pending",
        signature="",
    )
    db.add(job)
    db.commit()

    job_queue.enqueue(paw, job_id)
    log.info("[EXECUTE-ADHOC] Queued ad-hoc job for agent %s (job=%s executor=%s)", paw, job_id, executor)

    return {"job_id": job_id, "paw": paw, "queued": True}
