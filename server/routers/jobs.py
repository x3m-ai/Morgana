"""Jobs router - GET /api/v2/jobs/{job_id} for polling script execution output."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.job import Job
from models.test import Test

log = logging.getLogger("morgana.router.jobs")
router = APIRouter()


def _auth(key: Optional[str] = Header(None, alias="KEY")):
    if key != settings.api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), _=Depends(_auth)):
    """Return current status + output of a job (used by UI to poll for results)."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    test = db.query(Test).filter(Test.id == job.test_id).first()
    return {
        "id": job.id,
        "status": job.status,           # pending | dispatched | completed | failed
        "exit_code": test.exit_code if test else None,
        "stdout": (test.stdout or "") if test else "",
        "stderr": (test.stderr or "") if test else "",
        "duration_ms": (test.duration_ms or 0) if test else 0,
        "state": test.state if test else "pending",
    }
