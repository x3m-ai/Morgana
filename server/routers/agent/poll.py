"""Agent router: GET /api/v2/agent/poll - long-polling beacon endpoint.

The server holds the HTTP connection open for up to LONG_POLL_SECS when
nothing is immediately available. As soon as a job is enqueued or a console
session is created for this agent the response is returned instantly.

This means the agent can poll continuously without a sleep delay and still
see ~1s console/job latency instead of up to beacon_interval (30s).
"""

import asyncio
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
from core import console_sessions, poll_wake

log = logging.getLogger("morgana.router.poll")
router = APIRouter()

# Maximum seconds to hold an idle poll open before returning an empty response.
# Must be comfortably less than the agent's HTTP client timeout (35 s).
LONG_POLL_SECS = 28
LONG_POLL_TICK = 0.5  # re-check interval while waiting


def _authenticate_agent(authorization: Optional[str], paw: str, db: Session) -> Agent:
    ag = db.query(Agent).filter(Agent.paw == paw).first()
    if not ag:
        raise HTTPException(status_code=404, detail="Agent not found")
    return ag


def _sign_job(job: Job) -> str:
    # Return empty string so agent skips HMAC verification (dev mode).
    # The agent checks: if signature == "" -> allow.
    # Production: sign with the agent's own token stored server-side.
    return ""


@router.get("/poll")
async def poll(
    paw: str = Query(...),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    ag = _authenticate_agent(authorization, paw, db)
    ag.last_seen = datetime.utcnow()
    db.commit()

    # ------------------------------------------------------------------
    # 1. Check immediately - fast path
    # ------------------------------------------------------------------
    job_id = job_queue.dequeue(paw)
    console_paw = console_sessions.pending_paw(paw)

    if not job_id and not console_paw:
        # ------------------------------------------------------------------
        # 2. Nothing ready - enter long-poll hold
        # ------------------------------------------------------------------
        log.debug("[POLL] Agent %s: no work, entering long-poll (%ds)", paw, LONG_POLL_SECS)
        ag.status = "idle"
        db.commit()

        wake = poll_wake.get_or_create(paw)
        wake.clear()

        deadline = asyncio.get_event_loop().time() + LONG_POLL_SECS
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            try:
                await asyncio.wait_for(wake.wait(), timeout=min(LONG_POLL_TICK, remaining))
                wake.clear()
            except asyncio.TimeoutError:
                pass

            # Re-check for work after wake or tick
            job_id = job_queue.dequeue(paw)
            console_paw = console_sessions.pending_paw(paw)
            if job_id or console_paw:
                log.debug("[POLL] Agent %s: woke early - job=%s console=%s", paw, job_id, console_paw)
                break

        if not job_id and not console_paw:
            log.debug("[POLL] Agent %s: long-poll timeout, returning idle", paw)
            return {
                "job": None,
                "beacon_interval": ag.beacon_interval,
                "console_paw": None,
            }

    # Console only - no job
    if not job_id:
        log.debug("[POLL] Agent %s: console session pending", paw)
        return {
            "job": None,
            "beacon_interval": ag.beacon_interval,
            "console_paw": console_paw,
        }

    # ------------------------------------------------------------------
    # 3. Dispatch job
    # ------------------------------------------------------------------
    job = db.query(Job).filter(Job.id == job_id, Job.status == "pending").first()
    if not job:
        ag.status = "idle"
        db.commit()
        return {
            "job": None,
            "beacon_interval": ag.beacon_interval,
            "console_paw": console_paw,
        }

    job.status = "dispatched"
    job.dispatched_at = datetime.utcnow()

    test = db.query(Test).filter(Test.id == job.test_id).first()
    if test:
        test.state = "running"
        test.started_at = datetime.utcnow()

    ag.status = "busy"
    db.commit()

    sig = _sign_job(job)
    # sig is empty in dev mode - agent accepts unsigned jobs
    db.commit()

    input_args = {}
    if job.input_args:
        try:
            raw = json.loads(job.input_args)
            input_args = (
                {k: v.get("default") for k, v in raw.items()}
                if isinstance(raw, dict) and raw
                else raw
            )
        except Exception:
            pass

    log.info(
        "[POLL] Dispatching job %s to agent %s tcode=%s",
        job.id, paw, test.tcode if test else "?",
    )
    return {
        "job": {
            "id": job.id,
            "test_id": job.test_id,
            "executor": job.executor,
            "command": job.command,
            "cleanup_command": job.cleanup_command or "",
            "input_args": input_args,
            "download_url": job.download_url,
            "timeout_seconds": job.timeout_seconds or 300,
            "signature": sig,
        },
        "beacon_interval": ag.beacon_interval,
        "console_paw": console_sessions.pending_paw(paw),
    }