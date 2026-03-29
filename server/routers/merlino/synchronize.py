"""
Merlino router: POST /api/v2/merlino/synchronize
Receives the Tests table from Merlino and creates/queues jobs.
"""

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.agent import Agent
from models.test import Test
from models.job import Job
from models.script import Script
from core.job_queue import job_queue

log = logging.getLogger("morgana.router.synchronize")
router = APIRouter()


class MerlinoTestPayload(BaseModel):
    operation_id: Optional[str] = ""
    adversary_id: Optional[str] = ""
    operation: Optional[str] = ""
    adversary: Optional[str] = ""
    description: Optional[str] = ""
    tcodes: Optional[str] = ""
    assigned: Optional[str] = ""
    state: Optional[str] = "paused"
    agents: Optional[int] = 0
    group: Optional[str] = "red"


class SyncResponse(BaseModel):
    synced: int
    created: int
    updated: int
    agents_found: int
    jobs_queued: int
    operations: list


def _require_api_key(key: Optional[str] = Header(None, alias="KEY")):
    if key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.post("/synchronize")
async def synchronize(
    payload: List[MerlinoTestPayload],
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    created = 0
    updated = 0
    jobs_queued = 0
    operations_out = []

    agents_online = {a.hostname.upper(): a for a in db.query(Agent).all()}
    agents_by_name = {a.hostname: a for a in db.query(Agent).all()}

    for item in payload:
        is_new = False

        # Find or create Test record
        test = None
        if item.operation_id:
            test = db.query(Test).filter(Test.operation_id == item.operation_id).first()

        if test is None:
            test = Test(
                id=str(uuid.uuid4()),
                operation_id=item.operation_id or str(uuid.uuid4()),
                adversary_id=item.adversary_id or str(uuid.uuid4()),
                operation_name=item.operation,
                adversary_name=item.adversary,
                tcode=item.tcodes,
                assigned=item.assigned,
                group_name=item.group,
                state=item.state,
                created_at=datetime.utcnow(),
            )
            db.add(test)
            is_new = True
            created += 1
        else:
            test.state = item.state
            test.tcode = item.tcodes
            test.assigned = item.assigned
            test.group_name = item.group
            updated += 1

        # Resolve agent
        target_agent = None
        if item.assigned:
            target_agent = (
                agents_by_name.get(item.assigned)
                or agents_online.get(item.assigned.upper())
            )
        if target_agent:
            test.agent_id = target_agent.id

        db.flush()

        # Queue job if state is running and we have an agent
        if item.state == "running" and target_agent:
            first_script = _find_script_for_tcode(db, item.tcodes)
            if first_script:
                job = Job(
                    id=str(uuid.uuid4()),
                    test_id=test.id,
                    agent_id=target_agent.id,
                    script_id=first_script.id,
                    executor=first_script.executor,
                    command=first_script.command,
                    cleanup_command=first_script.cleanup_command,
                    input_args=first_script.input_args,
                    download_url=first_script.download_url,
                    status="pending",
                )
                db.add(job)
                job_queue.enqueue(target_agent.paw, job.id)
                jobs_queued += 1
                log.info("[SYNC] Job queued for agent %s test %s tcode %s", target_agent.paw, test.id, item.tcodes)

        operations_out.append({
            "operation_id": test.operation_id,
            "adversary_id": test.adversary_id,
            "operation": test.operation_name,
            "adversary": test.adversary_name,
            "state": test.state,
            "tcodes": test.tcode,
            "agents": 1 if test.agent_id else 0,
            "group": test.group_name,
        })

    db.commit()
    log.info("[SYNC] Completed: created=%d updated=%d jobs_queued=%d", created, updated, jobs_queued)

    return SyncResponse(
        synced=len(payload),
        created=created,
        updated=updated,
        agents_found=len(agents_online),
        jobs_queued=jobs_queued,
        operations=operations_out,
    )


def _find_script_for_tcode(db: Session, tcodes: str) -> Optional[Script]:
    """Find the first available script matching the first TCode."""
    if not tcodes:
        return None
    first_tcode = tcodes.split(",")[0].strip()
    return db.query(Script).filter(Script.tcode == first_tcode).first()
