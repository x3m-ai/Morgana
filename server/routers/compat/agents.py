"""Caldera-compatible GET /api/v2/agents endpoint for Merlino compatibility."""

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from config import settings
from core.auth import require_api_key
from database import get_db
from models.agent import Agent
from models.test import Test
from models.job import Job

router = APIRouter()


class AgentPatch(BaseModel):
    alias: Optional[str] = None
    beacon_interval: Optional[int] = None  # seconds, 5-3600; propagated on next poll


@router.get("/agents")
async def list_agents(db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    agents = db.query(Agent).all()
    return [{
        "paw": a.paw,
        "host": a.hostname,
        "alias": a.alias or "",
        "platform": a.platform,
        "os_version": a.os_version or "",
        "last_seen": a.last_seen.isoformat() if a.last_seen else None,
        "status": a.status,
        "beacon_interval": a.beacon_interval,
        "tags": a.tags or "",
        "agent_version": a.agent_version or "",
    } for a in agents]


@router.patch("/agents/{paw}")
async def patch_agent(paw: str, body: AgentPatch, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    agent = db.query(Agent).filter(Agent.paw == paw).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if body.alias is not None:
        agent.alias = body.alias.strip() or None
    if body.beacon_interval is not None:
        if not (5 <= body.beacon_interval <= 3600):
            raise HTTPException(status_code=400, detail="beacon_interval must be between 5 and 3600 seconds")
        agent.beacon_interval = body.beacon_interval
        # Wake the long-poll so the agent picks up the new interval immediately
        from core import poll_wake
        poll_wake.wake(paw)
    db.commit()
    return {"paw": agent.paw, "alias": agent.alias or "", "beacon_interval": agent.beacon_interval}


@router.delete("/agents/{paw}")
async def delete_agent(paw: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    agent = db.query(Agent).filter(Agent.paw == paw).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    # Remove dependent rows first (FK without CASCADE)
    db.query(Job).filter(Job.agent_id == agent.id).delete(synchronize_session=False)
    db.query(Test).filter(Test.agent_id == agent.id).delete(synchronize_session=False)
    db.delete(agent)
    db.commit()
    return {"deleted": paw}


@router.delete("/agents")
async def purge_stale_agents(
    older_than_hours: int = Query(default=24, ge=1),
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key)
):
    """Delete agents whose last_seen is older than `older_than_hours` hours."""
    cutoff = datetime.utcnow() - timedelta(hours=older_than_hours)
    stale = db.query(Agent).filter(
        (Agent.last_seen < cutoff) | (Agent.last_seen == None)  # noqa: E711
    ).all()
    paws = [a.paw for a in stale]
    for a in stale:
        db.query(Job).filter(Job.agent_id == a.id).delete(synchronize_session=False)
        db.query(Test).filter(Test.agent_id == a.id).delete(synchronize_session=False)
        db.delete(a)
    db.commit()
    return {"purged": len(paws), "paws": paws}
