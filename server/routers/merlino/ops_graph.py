"""Merlino router: ops-graph endpoints."""

import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.agent import Agent
from models.test import Test
from models.job import Job

log = logging.getLogger("morgana.router.ops_graph")
router = APIRouter()


def _require_api_key(key: Optional[str] = Header(None, alias="KEY")):
    if key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


class OpsGraphRequest(BaseModel):
    window_minutes: int = 60
    include_problems: bool = True


@router.post("/ops-graph")
async def ops_graph(
    body: OpsGraphRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    since = datetime.utcnow() - timedelta(minutes=body.window_minutes)
    tests = db.query(Test).filter(Test.created_at >= since).all()
    agents_map = {a.id: a for a in db.query(Agent).all()}

    nodes = []
    edges = []
    seen_agents = set()

    for t in tests:
        op_node_id = f"op-{t.id}"
        nodes.append({"id": op_node_id, "type": "operation", "label": t.operation_name or t.id, "state": t.state})

        if t.agent_id and t.agent_id not in seen_agents:
            seen_agents.add(t.agent_id)
            ag = agents_map.get(t.agent_id)
            if ag:
                ag_node_id = f"agent-{ag.id}"
                nodes.append({"id": ag_node_id, "type": "agent", "label": ag.hostname, "platform": ag.platform})
                edges.append({"source": ag_node_id, "target": op_node_id, "type": "agent_in_operation"})

        if t.state == "failed" or (t.exit_code is not None and t.exit_code != 0):
            prob_id = f"prob-{t.id}"
            nodes.append({"id": prob_id, "type": "problem", "label": f"{t.tcode or 'unknown'} failed", "severity": "high"})
            edges.append({"source": op_node_id, "target": prob_id, "type": "operation_has_problem"})

    return {
        "nodes": nodes,
        "edges": edges,
        "generatedAt": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/ops-graph/problem-details")
async def problem_details(
    problem_id: str = Query(...),
    window_minutes: int = Query(60),
    limit: int = Query(20),
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    test_id = problem_id.replace("prob-", "")
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Problem not found")
    ag = db.query(Agent).filter(Agent.id == test.agent_id).first() if test.agent_id else None
    return {
        "problem_id": problem_id,
        "label": f"{test.tcode or 'unknown'} failed",
        "tcode": test.tcode,
        "total_failures": 1,
        "recent_events": [{
            "ts": test.finished_at.isoformat() if test.finished_at else test.created_at.isoformat() if test.created_at else None,
            "agent_paw": ag.paw if ag else None,
            "agent_host": ag.hostname if ag else None,
            "exit_code": test.exit_code,
            "stderr_preview": (test.stderr or "")[:200],
        }],
    }


@router.get("/ops-graph/operation-details")
async def operation_details(
    operation_id: str = Query(...),
    window_minutes: int = Query(60),
    limit: int = Query(20),
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    test = db.query(Test).filter(
        (Test.id == operation_id) | (Test.operation_id == operation_id)
    ).first()
    if not test:
        raise HTTPException(status_code=404, detail="Operation not found")
    tcodes = [tc.strip() for tc in (test.tcode or "").split(",") if tc.strip()]
    ag = db.query(Agent).filter(Agent.id == test.agent_id).first() if test.agent_id else None
    return {
        "operation_id": test.operation_id or test.id,
        "name": test.operation_name or test.id,
        "state": test.state,
        "tcodes": tcodes,
        "steps": [{"step": i + 1, "script": tc, "tcode": tc, "status": test.state, "exit_code": test.exit_code if i == 0 else None} for i, tc in enumerate(tcodes)],
        "agents": [{"paw": ag.paw, "host": ag.hostname}] if ag else [],
    }


@router.get("/ops-graph/agent-details")
async def agent_details(
    agent_paw: str = Query(...),
    window_minutes: int = Query(60),
    limit: int = Query(20),
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    ag = db.query(Agent).filter(Agent.paw == agent_paw).first()
    if not ag:
        raise HTTPException(status_code=404, detail="Agent not found")
    since = datetime.utcnow() - timedelta(minutes=window_minutes)
    tests = db.query(Test).filter(Test.agent_id == ag.id, Test.created_at >= since).limit(limit).all()
    return {
        "paw": ag.paw,
        "host": ag.hostname,
        "platform": ag.platform,
        "status": ag.status,
        "last_seen": ag.last_seen.isoformat() if ag.last_seen else None,
        "active_tests": sum(1 for t in tests if t.state == "running"),
        "completed_tests": sum(1 for t in tests if t.state == "finished"),
        "failed_tests": sum(1 for t in tests if t.state == "failed"),
        "recent_activity": [{"ts": t.created_at.isoformat() if t.created_at else None, "tcode": t.tcode, "status": t.state} for t in tests],
    }
