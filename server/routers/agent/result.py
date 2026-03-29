"""Agent router: POST /api/v2/agent/result - job execution result."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.agent import Agent
from models.job import Job
from models.test import Test

log = logging.getLogger("morgana.router.result")
router = APIRouter()


class ResultRequest(BaseModel):
    paw: str
    job_id: str
    exit_code: int
    stdout: Optional[str] = ""
    stderr: Optional[str] = ""
    duration_ms: Optional[int] = 0


@router.post("/result")
async def result(body: ResultRequest, db: Session = Depends(get_db)):
    ag = db.query(Agent).filter(Agent.paw == body.paw).first()
    if not ag:
        raise HTTPException(status_code=404, detail="Agent not found")

    job = db.query(Job).filter(Job.id == body.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    now = datetime.utcnow()

    # Truncate output to max bytes
    max_bytes = settings.max_output_bytes
    stdout = (body.stdout or "")[:max_bytes]
    stderr = (body.stderr or "")[:max_bytes]

    job.status = "completed"
    job.completed_at = now

    test = db.query(Test).filter(Test.id == job.test_id).first()
    if test:
        test.exit_code = body.exit_code
        test.stdout = stdout
        test.stderr = stderr
        test.duration_ms = body.duration_ms
        test.finished_at = now
        test.state = "finished" if body.exit_code == 0 else "failed"

    ag.status = "idle"
    ag.last_seen = now
    db.commit()

    log.info(
        "[RESULT] Job %s agent=%s exit_code=%d duration=%dms state=%s",
        body.job_id, body.paw, body.exit_code, body.duration_ms or 0,
        test.state if test else "?"
    )

    return {"ack": True}
