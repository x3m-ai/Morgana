"""Agent router: POST /api/v2/agent/register - open enrollment, no auth required."""

import logging
import secrets
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.agent import Agent

log = logging.getLogger("morgana.router.register")
router = APIRouter()


class RegisterRequest(BaseModel):
    deploy_token: Optional[str] = ""  # accepted but ignored - no auth required
    hostname: str
    platform: str
    architecture: Optional[str] = "amd64"
    os_version: Optional[str] = None
    agent_version: Optional[str] = "0.1.0"


@router.post("/register")
async def register(body: RegisterRequest, db: Session = Depends(get_db)):
    paw = secrets.token_hex(8)  # 16-char hex ID - 64-bit space, collision-safe

    agent = Agent(
        id=str(uuid.uuid4()),
        paw=paw,
        hostname=body.hostname,
        platform=body.platform,
        architecture=body.architecture,
        os_version=body.os_version,
        agent_version=body.agent_version,
        status="online",
        last_seen=datetime.utcnow(),
        beacon_interval=settings.default_beacon_interval,
        enrolled_at=datetime.utcnow(),
    )
    db.add(agent)
    db.commit()

    log.info("[REGISTER] New agent enrolled: paw=%s host=%s platform=%s", paw, body.hostname, body.platform)

    return {
        "paw": paw,
        "agent_token": "",  # no token auth - agents connect freely,
        "server_cert_fingerprint": "self-signed",
        "beacon_interval": settings.default_beacon_interval,
        "work_dir": r"C:\ProgramData\Morgana\work" if body.platform == "windows" else "/var/lib/morgana/work",
    }
