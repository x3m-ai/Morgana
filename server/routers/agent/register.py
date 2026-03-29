"""Agent router: POST /api/v2/agent/register - one-time enrollment."""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.agent import Agent

log = logging.getLogger("morgana.router.register")
router = APIRouter()

# In-memory deploy token store (production: use DB or Redis)
_deploy_tokens: dict = {}


def create_deploy_token() -> str:
    token = secrets.token_urlsafe(32)
    _deploy_tokens[token] = {"used": False, "created_at": datetime.utcnow()}
    return token


def _validate_deploy_token(token: str) -> bool:
    entry = _deploy_tokens.get(token)
    if not entry or entry["used"]:
        # Allow the settings API key as a deploy token for simplicity
        return token == settings.api_key
    entry["used"] = True
    return True


class RegisterRequest(BaseModel):
    deploy_token: str
    hostname: str
    platform: str
    architecture: Optional[str] = "amd64"
    os_version: Optional[str] = None
    agent_version: Optional[str] = "0.1.0"


@router.post("/register")
async def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if not _validate_deploy_token(body.deploy_token):
        raise HTTPException(status_code=403, detail="Invalid or expired deploy token")

    paw = secrets.token_hex(4)  # Short 8-char hex ID
    agent_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(agent_token.encode()).hexdigest()

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
        token_hash=token_hash,
        enrolled_at=datetime.utcnow(),
        enrolled_by=hashlib.sha256(body.deploy_token.encode()).hexdigest(),
    )
    db.add(agent)
    db.commit()

    log.info("[REGISTER] New agent enrolled: paw=%s host=%s platform=%s", paw, body.hostname, body.platform)

    return {
        "paw": paw,
        "agent_token": agent_token,
        "server_cert_fingerprint": "self-signed",
        "beacon_interval": settings.default_beacon_interval,
        "work_dir": r"C:\ProgramData\Morgana\work" if body.platform == "windows" else "/var/lib/morgana/work",
    }
