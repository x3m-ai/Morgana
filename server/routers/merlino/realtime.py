"""Merlino router: GET /api/v2/merlino/realtime"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from config import settings
from database import get_db
from models.agent import Agent
from models.test import Test

log = logging.getLogger("morgana.router.realtime")
router = APIRouter()


def _require_api_key(key: Optional[str] = Header(None, alias="KEY")):
    if key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.get("/realtime")
async def realtime(
    window: str = Query("15m"),
    include_timeline: bool = Query(True),
    timeline_limit: int = Query(250),
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    window_map = {"5m": 5, "15m": 15, "1h": 60, "6h": 360, "24h": 1440}
    minutes = window_map.get(window, 15)
    since = datetime.utcnow() - timedelta(minutes=minutes)

    tests = db.query(Test).filter(Test.created_at >= since).all()
    agents = db.query(Agent).all()

    operations = []
    for t in tests:
        tcodes = [tc.strip() for tc in (t.tcode or "").split(",") if tc.strip()]
        success = 1 if t.exit_code == 0 and t.state == "finished" else 0
        failed = 1 if t.exit_code not in (None, 0) and t.state in ("failed", "finished") else 0
        running = 1 if t.state == "running" else 0
        operations.append({
            "id": t.operation_id or t.id,
            "name": t.operation_name or t.id,
            "adversary": t.adversary_name,
            "state": t.state,
            "started": t.started_at.isoformat() if t.started_at else t.created_at.isoformat() if t.created_at else None,
            "finish_time": t.finished_at.isoformat() if t.finished_at else None,
            "total_abilities": len(tcodes) or 1,
            "success_count": success,
            "error_count": failed,
            "running_count": running,
            "agents_count": 1 if t.agent_id else 0,
            "techniques_count": len(tcodes),
            "tcodes": tcodes,
            "abilities": [{"name": f"Test {tc}", "tactic": "", "technique": tc, "status": t.state} for tc in tcodes],
        })

    agent_list = [{
        "paw": a.paw,
        "host": a.hostname,
        "platform": a.platform,
        "last_seen": a.last_seen.isoformat() if a.last_seen else None,
    } for a in agents]

    total_success = sum(o["success_count"] for o in operations)
    total_errors = sum(o["error_count"] for o in operations)
    total_abilities = sum(o["total_abilities"] for o in operations)
    total_success_rate = round((total_success / total_abilities * 100) if total_abilities else 0, 1)

    global_stats = {
        "totalOps": len(operations),
        "totalAbilities": total_abilities,
        "totalSuccess": total_success,
        "totalErrors": total_errors,
        "successRate": total_success_rate,
        "runningOps": sum(1 for o in operations if o["state"] == "running"),
        "completedOps": sum(1 for o in operations if o["state"] == "finished"),
        "failedOps": sum(1 for o in operations if o["state"] == "failed"),
        "totalAgents": len(agents),
    }

    return {
        "operations": operations,
        "agents": agent_list,
        "globalStats": global_stats,
        "timeline": [],
        "generatedAt": datetime.utcnow().isoformat() + "Z",
        "window": window,
    }
