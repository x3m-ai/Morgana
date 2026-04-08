"""Tests router - CRUD for Test execution records.

GET    /api/v2/tests              list tests (newest first, optional limit)
GET    /api/v2/tests/{id}         single test detail (includes stdout/stderr)
DELETE /api/v2/tests/{id}         delete a single test + its jobs
DELETE /api/v2/tests              delete ALL tests + jobs
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from config import settings
from core.auth import require_api_key
from database import get_db
from models.test import Test
from models.job import Job
from models.agent import Agent

log = logging.getLogger("morgana.router.tests")
router = APIRouter()


def _fmt(dt):
    return dt.isoformat() + "Z" if dt else None


def _test_row(t: Test, agent: Optional[Agent] = None):
    return {
        "id": t.id,
        "tcode": t.tcode,
        "operation_name": t.operation_name,
        "adversary_name": t.adversary_name,
        "state": t.state,
        "exit_code": t.exit_code,
        "duration_ms": t.duration_ms,
        "created_at": _fmt(t.created_at),
        "started_at": _fmt(t.started_at),
        "finished_at": _fmt(t.finished_at),
        "agent_paw": agent.paw if agent else None,
        "agent_hostname": agent.hostname if agent else None,
        "stdout": t.stdout,
        "stderr": t.stderr,
    }


@router.get("")
def list_tests(
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    tests = db.query(Test).order_by(Test.created_at.desc()).limit(limit).all()
    agents = {a.id: a for a in db.query(Agent).all()}
    return [_test_row(t, agents.get(t.agent_id)) for t in tests]


@router.get("/{test_id}")
def get_test(test_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    t = db.query(Test).filter(Test.id == test_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Test not found")
    agent = db.query(Agent).filter(Agent.id == t.agent_id).first() if t.agent_id else None
    return _test_row(t, agent)


@router.delete("/{test_id}", status_code=204)
def delete_test(test_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    t = db.query(Test).filter(Test.id == test_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Test not found")
    db.query(Job).filter(Job.test_id == test_id).delete()
    db.delete(t)
    db.commit()
    log.info("[TEST] Deleted test %s", test_id)


@router.delete("", status_code=204)
def delete_all_tests(db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    count = db.query(Test).count()
    # Delete jobs first (FK constraint: jobs.test_id -> tests.id)
    db.query(Job).delete(synchronize_session=False)
    db.query(Test).delete(synchronize_session=False)
    db.commit()
    log.info("[TEST] Deleted all tests (%d records)", count)
