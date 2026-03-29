"""Agent router: GET /api/v2/agent/poll - beacon polling endpoint."""

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.agent import Agent
from models.job import Job
from models.test import Test
from core.job_queue import job_queue

log = logging.getLogger("morgana.router.poll")
router = APIRouter()


def _authenticate_agent(authorization: Optional[str], paw: str, db: Session) -> Agent:
    ag = db.query(Agent).filter(Agent.paw == paw).first()
    if not ag:
        raise HTTPException(status_code=404, detail="Agent not found")
    if authorization:
        token = authorization.replace("Bearer ", "")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        if ag.token_hash and ag.token_hash != token_hash:
            raise HTTPException(status_code=401, detail="Invalid agent token")
    return ag


def _sign_job(job: Job) -> str:
    payload = f"{job.id}:{job.command}:{job.executor}"
    return hmac.new(settings.hmac_secret.encode(), payload.encode(), "sha256").hexdigest()


@router.get("/poll")
async def poll(
    paw: str = Query(...),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    ag = _authenticate_agent(authorization, paw, db)
    ag.last_seen = datetime.utcnow()

    job_id = job_queue.dequeue(paw)
    if not job_id:
        ag.status = "idle"
        db.commit()
        log.debug("[POLL] Agent %s: no jobs pending", paw)
        return {"job": None, "beacon_interval": ag.beacon_interval}

    job = db.query(Job).filter(Job.id == job_id, Job.status == "pending").first()
    if not job:
        ag.status = "idle"
        db.commit()
        return {"job": None, "beacon_interval": ag.beacon_interval}

    job.status = "dispatched"
    job.dispatched_at = datetime.utcnow()

    test = db.query(Test).filter(Test.id == job.test_id).first()
    if test:
        test.state = "running"
        test.started_at = datetime.utcnow()

    ag.status = "busy"
    db.commit()

    sig = _sign_job(job)
    job.signature = sig
    db.commit()

    input_args = {}
    if job.input_args:
        try:
            raw = json.loads(job.input_args)
            input_args = {k: v.get("default") for k, v in raw.items()} if isinstance(raw, dict) and raw else raw
        except Exception:
            pass

    log.info("[POLL] Dispatching job %s to agent %s tcode=%s", job.id, paw, test.tcode if test else "?")

    return {
        "job": {
            "id": job.id,
            "test_id": job.test_id,
            "executor": job.executor,
            "command": job.command,
            "cleanup_command": job.cleanup_command,
            "input_args": input_args,
            "download_url": job.download_url,
            "timeout_seconds": job.timeout_seconds or 300,
            "signature": sig,
        },
        "beacon_interval": ag.beacon_interval,
    }
