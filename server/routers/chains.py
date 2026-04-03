"""
Morgana - Chains router
CRUD for Chains + background execution engine + execution log API.

Routes (registered with prefix /api/v2/chains):
  GET    ""                          list all chains
  POST   ""                          create chain
  POST   "/import"                   import chain from JSON
  GET    "/executions"               list chain executions
  GET    "/executions/{exec_id}"     get execution detail
  GET    "/executions/{exec_id}/log" full post-mortem step log
  GET    "/{chain_id}"               get chain with flow
  PUT    "/{chain_id}"               update chain
  DELETE "/{chain_id}"               delete chain
  POST   "/{chain_id}/execute"       start background execution
"""

import json
import logging
import threading
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from database import SessionLocal
from models.chain import Chain
from models.chain_execution import ChainExecution
from models.agent import Agent
from models.script import Script
from models.test import Test
from models.job import Job
from core.job_queue import job_queue

log = logging.getLogger("morgana.chains")

router = APIRouter()


# ─── DB dependency ───────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class ChainCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    flow: Optional[dict] = None     # {"nodes": [...]}
    agent_paw: Optional[str] = None


class ChainUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    flow: Optional[dict] = None
    agent_paw: Optional[str] = None


class ExecuteRequest(BaseModel):
    agent_paw: Optional[str] = None  # if omitted, use chain's default agent_paw


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _chain_to_dict(c: Chain) -> dict:
    flow = {}
    try:
        flow = json.loads(c.flow_json or '{"nodes":[]}')
    except Exception:
        flow = {"nodes": []}
    return {
        "id":          c.id,
        "name":        c.name,
        "description": c.description or "",
        "agent_paw":   c.agent_paw or "",
        "objective":   c.objective or "",
        "author":      c.author or "",
        "tags":        c.tags or "",
        "flow":        flow,
        "created_at":  c.created_at.isoformat() if c.created_at else None,
        "updated_at":  c.updated_at.isoformat() if c.updated_at else None,
    }


def _exec_to_dict(e: ChainExecution, include_steps: bool = False) -> dict:
    d = {
        "id":             e.id,
        "chain_id":       e.chain_id,
        "chain_name":     e.chain_name,
        "agent_paw":      e.agent_paw,
        "agent_hostname": e.agent_hostname or "",
        "state":          e.state,
        "started_at":     e.started_at.isoformat() if e.started_at else None,
        "finished_at":    e.finished_at.isoformat() if e.finished_at else None,
        "error":          e.error or "",
    }
    if include_steps:
        try:
            d["steps"] = json.loads(e.step_logs or "[]")
        except Exception:
            d["steps"] = []
        try:
            d["flow_snapshot"] = json.loads(e.flow_snapshot or '{"nodes":[]}')
        except Exception:
            d["flow_snapshot"] = {"nodes": []}
    return d


# ─── Routes: fixed paths FIRST to avoid shadowing by /{chain_id} ─────────────

@router.get("")
def list_chains(db: Session = Depends(get_db)):
    chains = db.query(Chain).order_by(Chain.updated_at.desc()).all()
    return [_chain_to_dict(c) for c in chains]


@router.post("")
def create_chain(body: ChainCreate, db: Session = Depends(get_db)):
    flow_str = json.dumps(body.flow or {"nodes": []})
    c = Chain(
        name=body.name,
        description=body.description or "",
        flow_json=flow_str,
        agent_paw=body.agent_paw or None,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    log.info("[SUCCESS] Chain created: %s (%s)", c.name, c.id)
    return _chain_to_dict(c)


@router.post("/import")
def import_chain(body: dict, db: Session = Depends(get_db)):
    """Accept a full chain JSON export and create a new chain from it."""
    name = body.get("name", "Imported Chain") + " (imported)"
    description = body.get("description", "")
    flow = body.get("flow", {"nodes": []})
    c = Chain(
        name=name,
        description=description,
        flow_json=json.dumps(flow),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    log.info("[SUCCESS] Chain imported: %s (%s)", c.name, c.id)
    return _chain_to_dict(c)


@router.get("/executions")
def list_executions(chain_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(ChainExecution).order_by(ChainExecution.started_at.desc())
    if chain_id:
        q = q.filter(ChainExecution.chain_id == chain_id)
    execs = q.limit(200).all()
    return [_exec_to_dict(e) for e in execs]


@router.get("/executions/{exec_id}")
def get_execution(exec_id: str, db: Session = Depends(get_db)):
    e = db.query(ChainExecution).filter(ChainExecution.id == exec_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Execution not found")
    return _exec_to_dict(e, include_steps=True)


@router.get("/executions/{exec_id}/log")
def get_execution_log(exec_id: str, db: Session = Depends(get_db)):
    """Post-mortem execution log - full step details including outputs."""
    e = db.query(ChainExecution).filter(ChainExecution.id == exec_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Execution not found")
    try:
        steps = json.loads(e.step_logs or "[]")
    except Exception:
        steps = []
    try:
        flow_snapshot = json.loads(e.flow_snapshot or '{"nodes":[]}')
    except Exception:
        flow_snapshot = {"nodes": []}
    return {
        "execution_id":   e.id,
        "chain_id":       e.chain_id,
        "chain_name":     e.chain_name,
        "agent_paw":      e.agent_paw,
        "agent_hostname": e.agent_hostname or "",
        "state":          e.state,
        "started_at":     e.started_at.isoformat() if e.started_at else None,
        "finished_at":    e.finished_at.isoformat() if e.finished_at else None,
        "error":          e.error or "",
        "flow_snapshot":  flow_snapshot,
        "steps":          steps,
    }


# ─── Routes: parameterized paths AFTER fixed paths ───────────────────────────

@router.get("/{chain_id}")
def get_chain(chain_id: str, db: Session = Depends(get_db)):
    c = db.query(Chain).filter(Chain.id == chain_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Chain not found")
    return _chain_to_dict(c)


@router.put("/{chain_id}")
def update_chain(chain_id: str, body: ChainUpdate, db: Session = Depends(get_db)):
    c = db.query(Chain).filter(Chain.id == chain_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Chain not found")
    if body.name is not None:
        c.name = body.name
    if body.description is not None:
        c.description = body.description
    if body.flow is not None:
        c.flow_json = json.dumps(body.flow)
    if body.agent_paw is not None:
        c.agent_paw = body.agent_paw or None
    c.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(c)
    log.info("[SUCCESS] Chain updated: %s (%s)", c.name, c.id)
    return _chain_to_dict(c)


@router.delete("/{chain_id}")
def delete_chain(chain_id: str, db: Session = Depends(get_db)):
    c = db.query(Chain).filter(Chain.id == chain_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Chain not found")
    # Nullify chain_id on related executions so history is preserved
    db.query(ChainExecution).filter(ChainExecution.chain_id == chain_id).update({"chain_id": None})
    db.delete(c)
    db.commit()
    log.info("[SUCCESS] Chain deleted: %s", chain_id)
    return {"deleted": chain_id}


@router.post("/{chain_id}/execute")
def execute_chain(chain_id: str, body: ExecuteRequest, db: Session = Depends(get_db)):
    """Start a background execution of this chain on the given agent."""
    c = db.query(Chain).filter(Chain.id == chain_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Chain not found")

    # Resolve agent: use body.agent_paw if provided, otherwise fall back to chain's default
    paw = (body.agent_paw or "").strip() or (c.agent_paw or "").strip()
    if not paw:
        raise HTTPException(status_code=400, detail="No agent selected. Set a default agent on the chain or pass agent_paw.")
    agent = db.query(Agent).filter(Agent.paw == paw).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {paw}")

    # Parse flow
    try:
        flow = json.loads(c.flow_json or '{"nodes":[]}')
        nodes = flow.get("nodes", [])
    except Exception:
        nodes = []

    if not nodes:
        raise HTTPException(status_code=400, detail="Chain has no nodes - add scripts first")

    # Create execution record
    exec_id = str(uuid.uuid4())
    execution = ChainExecution(
        id=exec_id,
        chain_id=c.id,
        chain_name=c.name,
        agent_id=agent.id,
        agent_paw=agent.paw,
        agent_hostname=agent.hostname or agent.paw,
        state="running",
        flow_snapshot=c.flow_json,
        step_logs="[]",
    )
    db.add(execution)
    db.commit()

    log.info("[START] Chain execution %s - chain=%s agent=%s", exec_id, c.name, agent.paw)

    # Spawn background thread
    t = threading.Thread(
        target=_run_chain,
        args=(exec_id, nodes, agent.paw, c.name),
        daemon=True,
    )
    t.start()

    return {"execution_id": exec_id, "state": "running"}


# ─── Background execution engine ──────────────────────────────────────────────

def _run_chain(exec_id: str, nodes: list, agent_paw: str, chain_name: str = ""):
    """Background thread: walk nodes, dispatch jobs, record step logs."""
    db = SessionLocal()
    step_logs = []
    try:
        last_stdout = ""
        last_stdout = _walk_nodes(db, exec_id, nodes, agent_paw, chain_name, step_logs, last_stdout)
        _finish_execution(db, exec_id, "completed", step_logs, None)
        log.info("[SUCCESS] Chain execution %s completed (%d steps)", exec_id, len(step_logs))
    except Exception as exc:
        log.exception("[ERROR] Chain execution %s failed: %s", exec_id, exc)
        _finish_execution(db, exec_id, "failed", step_logs, str(exc))
    finally:
        db.close()


def _walk_nodes(db: Session, exec_id: str, nodes: list, agent_paw: str,
                chain_name: str, step_logs: list, last_stdout: str) -> str:
    """Recurse through a node list, executing scripts and branching on if_else."""
    for node in nodes:
        ntype = node.get("type", "script")

        if ntype == "script":
            result = _run_script_node(db, node, agent_paw, chain_name, step_logs)
            last_stdout = result.get("stdout", "")
            _update_execution_logs(db, exec_id, step_logs)

        elif ntype == "if_else":
            contains = (node.get("contains") or "").lower().strip()
            matched = contains != "" and contains in last_stdout.lower()
            branch_taken = "if" if matched else "else"

            step_logs.append({
                "node_id":     node.get("id", ""),
                "type":        "if_else",
                "contains":    contains,
                "matched":     matched,
                "branch_taken": branch_taken,
                "last_stdout_snippet": last_stdout[:200],
            })
            _update_execution_logs(db, exec_id, step_logs)

            branch_nodes = node.get("if_nodes", []) if matched else node.get("else_nodes", [])
            last_stdout = _walk_nodes(db, exec_id, branch_nodes, agent_paw, chain_name, step_logs, last_stdout)

        elif ntype == "parallel":
            node_id  = node.get("id", "")
            branches = node.get("branches", [])

            par_entry = {
                "node_id":  node_id,
                "type":     "parallel",
                "state":    "running",
                "branches": [],
            }
            idx_in_logs = len(step_logs)
            step_logs.append(par_entry)
            _update_execution_logs(db, exec_id, step_logs)

            branch_results = [None] * len(branches)
            lock = threading.Lock()

            def run_branch(branch_idx: int, branch_nodes: list):
                b_logs = []
                try:
                    b_last = _walk_nodes(db, exec_id, branch_nodes, agent_paw, chain_name, b_logs, last_stdout)
                    with lock:
                        branch_results[branch_idx] = {
                            "branch_index": branch_idx,
                            "state":        "completed",
                            "steps":        b_logs,
                            "last_stdout":  b_last,
                        }
                except Exception as exc:
                    with lock:
                        branch_results[branch_idx] = {
                            "branch_index": branch_idx,
                            "state":        "failed",
                            "error":        str(exc),
                            "steps":        b_logs,
                        }

            threads = [
                threading.Thread(target=run_branch, args=(i, branch), daemon=True)
                for i, branch in enumerate(branches)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            all_ok = all(r and r.get("state") == "completed" for r in branch_results)
            step_logs[idx_in_logs]["state"]    = "completed" if all_ok else "partial"
            step_logs[idx_in_logs]["branches"] = [
                r or {"branch_index": i, "state": "failed", "steps": []}
                for i, r in enumerate(branch_results)
            ]
            _update_execution_logs(db, exec_id, step_logs)
            # Parallel branches run independently; last_stdout stays as it was before parallel

    return last_stdout


def _run_script_node(db: Session, node: dict, agent_paw: str, chain_name: str, step_logs: list) -> dict:
    """Create a Test+Job, enqueue on agent, poll until done, return outputs."""
    script_id = node.get("script_id")
    node_id   = node.get("id", "")

    if not script_id:
        entry = {
            "node_id": node_id,
            "type":    "script",
            "tcode":   node.get("tcode", ""),
            "name":    node.get("script_name", ""),
            "state":   "failed",
            "exit_code": -1,
            "stdout":  "",
            "stderr":  "No script_id in node",
        }
        step_logs.append(entry)
        return entry

    s = db.query(Script).filter(Script.id == script_id).first()
    if not s:
        entry = {
            "node_id": node_id,
            "type":    "script",
            "tcode":   node.get("tcode", ""),
            "name":    node.get("script_name", ""),
            "state":   "failed",
            "exit_code": -1,
            "stdout":  "",
            "stderr":  f"Script not found: {script_id}",
        }
        step_logs.append(entry)
        return entry

    agent = db.query(Agent).filter(Agent.paw == agent_paw).first()
    if not agent:
        entry = {
            "node_id": node_id,
            "type":    "script",
            "tcode":   s.tcode or "",
            "name":    s.name or "",
            "state":   "failed",
            "exit_code": -1,
            "stdout":  "",
            "stderr":  f"Agent not found: {agent_paw}",
        }
        step_logs.append(entry)
        return entry

    # Create Test + Job (same pattern as scripts.py execute endpoint)
    test_id = str(uuid.uuid4())
    job_id  = str(uuid.uuid4())

    test = Test(
        id=test_id,
        script_id=s.id,
        tcode=s.tcode,
        agent_id=agent.id,
        operation_name=f"chain:{chain_name or s.name}",
        state="pending",
    )
    db.add(test)
    db.flush()

    job = Job(
        id=job_id,
        test_id=test.id,
        agent_id=agent.id,
        script_id=s.id,
        executor=s.executor,
        command=s.command,
        cleanup_command=s.cleanup_command,
        timeout_seconds=300,
        status="pending",
        signature="",
    )
    db.add(job)
    db.commit()

    job_queue.enqueue(agent_paw, job_id)
    log.info("[START] Chain node %s - script=%s job=%s", node_id, s.name, job_id)

    # Poll until job is completed (max 5 min)
    deadline = time.time() + 310
    while time.time() < deadline:
        time.sleep(3)
        db.expire(job)
        db.expire(test)
        refreshed_job = db.query(Job).filter(Job.id == job_id).first()
        if refreshed_job and refreshed_job.status == "completed":
            break

    refreshed_test = db.query(Test).filter(Test.id == test_id).first()
    state = refreshed_test.state if refreshed_test else "failed"
    stdout_val    = (refreshed_test.stdout    or "") if refreshed_test else ""
    stderr_val    = (refreshed_test.stderr    or "") if refreshed_test else ""
    exit_code_val = (refreshed_test.exit_code)       if (refreshed_test and refreshed_test.exit_code is not None) else -1

    entry = {
        "node_id":   node_id,
        "type":      "script",
        "tcode":     s.tcode or "",
        "name":      s.name or "",
        "state":     state,
        "exit_code": exit_code_val,
        "stdout":    stdout_val,
        "stderr":    stderr_val,
        "test_id":   test_id,
        "job_id":    job_id,
    }
    step_logs.append(entry)
    log.info("[SUCCESS] Chain node %s done - state=%s", node_id, state)
    return entry


def _update_execution_logs(db: Session, exec_id: str, step_logs: list):
    """Persist current step_logs to the execution record mid-run."""
    try:
        db.query(ChainExecution).filter(ChainExecution.id == exec_id).update(
            {"step_logs": json.dumps(step_logs)}
        )
        db.commit()
    except Exception as exc:
        log.warning("[WARN] Could not update execution logs for %s: %s", exec_id, exc)


def _finish_execution(db: Session, exec_id: str, state: str, step_logs: list, error: Optional[str]):
    """Mark execution as completed or failed."""
    try:
        db.query(ChainExecution).filter(ChainExecution.id == exec_id).update({
            "state":       state,
            "step_logs":   json.dumps(step_logs),
            "finished_at": datetime.utcnow(),
            "error":       error or "",
        })
        db.commit()
    except Exception as exc:
        log.error("[ERROR] Could not finish execution %s: %s", exec_id, exc)
