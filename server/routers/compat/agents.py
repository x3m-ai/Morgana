"""Caldera-compatible GET /api/v2/agents endpoint for Merlino compatibility."""

from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from config import settings
from database import get_db
from models.agent import Agent

router = APIRouter()


def _require_api_key(key: Optional[str] = Header(None, alias="KEY")):
    if key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


class AgentPatch(BaseModel):
    alias: Optional[str] = None


@router.get("/agents")
async def list_agents(db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
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
    } for a in agents]


@router.patch("/agents/{paw}")
async def patch_agent(paw: str, body: AgentPatch, db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    agent = db.query(Agent).filter(Agent.paw == paw).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if body.alias is not None:
        agent.alias = body.alias.strip() or None
    db.commit()
    return {"paw": agent.paw, "alias": agent.alias or ""}
