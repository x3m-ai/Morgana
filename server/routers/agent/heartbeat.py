"""Agent router: POST /api/v2/agent/heartbeat."""

from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from database import get_db
from models.agent import Agent

router = APIRouter()


class HeartbeatRequest(BaseModel):
    paw: str
    status: Optional[str] = "idle"
    ip_address: Optional[str] = None


@router.post("/heartbeat")
async def heartbeat(body: HeartbeatRequest, db: Session = Depends(get_db)):
    ag = db.query(Agent).filter(Agent.paw == body.paw).first()
    if ag:
        ag.last_seen = datetime.utcnow()
        ag.status = body.status or "idle"
        if body.ip_address:
            ag.ip_address = body.ip_address
        db.commit()
    return {"ack": True, "beacon_interval": ag.beacon_interval if ag else 30}
