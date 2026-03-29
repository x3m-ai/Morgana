"""Caldera-compatible GET /api/v2/agents endpoint for Merlino compatibility."""

from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from config import settings
from database import get_db
from models.agent import Agent

router = APIRouter()


def _require_api_key(key: Optional[str] = Header(None, alias="KEY")):
    if key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.get("/agents")
async def list_agents(db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    agents = db.query(Agent).all()
    return [{
        "paw": a.paw,
        "host": a.hostname,
        "platform": a.platform,
        "last_seen": a.last_seen.isoformat() if a.last_seen else None,
        "status": a.status,
    } for a in agents]
