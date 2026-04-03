"""Campaigns router - sequence of Chains with optional parallel branches."""

import json
import logging
import threading
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal, get_db
from models.campaign import Campaign
from models.campaign_execution import CampaignExecution
from models.chain import Chain
from models.chain_execution import ChainExecution
from models.agent import Agent
from routers.chains import _run_chain as _run_chain_fn

log = logging.getLogger("morgana.router.campaigns")
router = APIRouter()


def _require_api_key(key: Optional[str] = Header(None, alias="KEY")):
    if key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    flow_json: Optional[str] = '{"nodes":[]}'
    agent_paw: Optional[str] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    flow_json: Optional[str] = None
    agent_paw: Optional[str] = None


class ExecuteRequest(BaseModel):
    agent_paw: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _count_chain_nodes(nodes: list) -> int:
    count = 0
    for n in nodes:
        if n.get("type") == "chain":
            count += 1
        elif n.get("type") == "parallel":
            for branch in n.get("branches", []):
                count += _count_chain_nodes(branch)
    return count


def _campaign_to_dict(c: Campaign) -> dict:
    try:
        flow = json.loads(c.flow_json or '{"nodes":[]}')
    except Exception:
        flow = {"nodes": []}
    return {
        "id":          c.id,
        "name":        c.name,
        "description": c.description or "",
        "flow_json":   c.flow_json or '{"nodes":[]}',
        "flow":        flow,
        "agent_paw":   c.agent_paw or "",
        "node_count":  _count_chain_nodes(flow.get("nodes", [])),
        "created_at":  c.created_at.isoformat() if c.created_at else None,
        "updated_at":  c.updated_at.isoformat() if c.updated_at else None,
    }


def _exec_to_dict(e: CampaignExecution) -> dict:
    return {
        "id":             e.id,
        "campaign_id":    e.campaign_id,
        "campaign_name":  e.campaign_name,
        "agent_paw":      e.agent_paw,
        "agent_hostname": e.agent_hostname,
        "state":          e.state,
        "started_at":     e.started_at.isoformat() if e.started_at else None,
        "finished_at":    e.finished_at.isoformat() if e.finished_at else None,
        "error":          e.error,
    }


# ─── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("")
def list_campaigns(db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    return [_campaign_to_dict(c) for c in db.query(Campaign).order_by(Campaign.created_at.desc()).all()]


@router.post("")
def create_campaign(body: CampaignCreate, db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    c = Campaign(
        id=str(uuid.uuid4()),
        name=body.name,
        description=body.description or "",
        flow_json=body.flow_json or '{"nodes":[]}',
        agent_paw=body.agent_paw or None,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    log.info("[CAMPAIGN] Created: %s (%s)", c.name, c.id)
    return _campaign_to_dict(c)


@router.get("/executions")
def list_executions(db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    execs = db.query(CampaignExecution).order_by(CampaignExecution.started_at.desc()).limit(50).all()
    return [_exec_to_dict(e) for e in execs]


@router.get("/executions/{exec_id}/log")
def get_execution_log(exec_id: str, db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    e = db.query(CampaignExecution).filter(CampaignExecution.id == exec_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Execution not found")
    try:
        logs = json.loads(e.step_logs or "[]")
    except Exception:
        logs = []
    return {**_exec_to_dict(e), "step_logs": logs}


@router.get("/{campaign_id}")
def get_campaign(campaign_id: str, db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _campaign_to_dict(c)


@router.put("/{campaign_id}")
def update_campaign(campaign_id: str, body: CampaignUpdate, db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if body.name is not None:
        c.name = body.name
    if body.description is not None:
        c.description = body.description
    if body.flow_json is not None:
        c.flow_json = body.flow_json
    if body.agent_paw is not None:
        c.agent_paw = body.agent_paw or None
    c.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(c)
    log.info("[CAMPAIGN] Updated: %s (%s)", c.name, c.id)
    return _campaign_to_dict(c)


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: str, db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    name = c.name
    db.delete(c)
    db.commit()
    log.info("[CAMPAIGN] Deleted: %s (%s)", name, campaign_id)
    return {"ok": True}


@router.post("/{campaign_id}/execute")
def execute_campaign(campaign_id: str, body: ExecuteRequest, db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")

    agent_paw = body.agent_paw or c.agent_paw
    if not agent_paw:
        raise HTTPException(status_code=400, detail="No agent specified. Set a default agent on the campaign or pass agent_paw.")

    agent = db.query(Agent).filter(Agent.paw == agent_paw).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_paw}")

    try:
        flow = json.loads(c.flow_json or '{"nodes":[]}')
        nodes = flow.get("nodes", [])
    except Exception:
        nodes = []

    if not nodes:
        raise HTTPException(status_code=400, detail="Campaign has no nodes - add chains first")

    exec_id = str(uuid.uuid4())
    execution = CampaignExecution(
        id=exec_id,
        campaign_id=c.id,
        campaign_name=c.name,
        agent_id=agent.id,
        agent_paw=agent.paw,
        agent_hostname=agent.hostname or agent.paw,
        state="running",
        flow_snapshot=c.flow_json,
        step_logs="[]",
    )
    db.add(execution)
    db.commit()

    log.info("[START] Campaign execution %s - campaign=%s agent=%s", exec_id, c.name, agent.paw)

    t = threading.Thread(
        target=_run_campaign,
        args=(exec_id, nodes, agent.paw, c.name),
        daemon=True,
    )
    t.start()

    return {"execution_id": exec_id, "state": "running"}


# ─── Background execution engine ──────────────────────────────────────────────

def _run_campaign(exec_id: str, nodes: list, agent_paw: str, campaign_name: str = ""):
    """Background thread: walk campaign nodes, dispatch chains/parallels, record logs."""
    db = SessionLocal()
    step_logs = []
    try:
        _walk_campaign_nodes(db, exec_id, nodes, agent_paw, step_logs, "")
        _finish_campaign(db, exec_id, "completed", step_logs, None)
        log.info("[SUCCESS] Campaign execution %s completed (%d steps)", exec_id, len(step_logs))
    except Exception as exc:
        log.exception("[ERROR] Campaign execution %s failed: %s", exec_id, exc)
        _finish_campaign(db, exec_id, "failed", step_logs, str(exc))
    finally:
        db.close()


def _finish_campaign(db, exec_id: str, state: str, step_logs: list, error: Optional[str]):
    e = db.query(CampaignExecution).filter(CampaignExecution.id == exec_id).first()
    if e:
        e.state = state
        e.step_logs = json.dumps(step_logs)
        e.finished_at = datetime.utcnow()
        e.error = error
        db.commit()


def _update_campaign_logs(db, exec_id: str, step_logs: list):
    e = db.query(CampaignExecution).filter(CampaignExecution.id == exec_id).first()
    if e:
        e.step_logs = json.dumps(step_logs)
        db.commit()


def _walk_campaign_nodes(db, exec_id: str, nodes: list, agent_paw: str,
                         step_logs: list, last_output: str = "") -> str:
    """Walk campaign nodes sequentially, dispatching chains, parallels, and if/else."""
    for node in nodes:
        ntype = node.get("type", "chain")
        if ntype == "chain":
            result = _run_chain_step(node, agent_paw)
            step_logs.append(result)
            _update_campaign_logs(db, exec_id, step_logs)
            # Track last stdout for if/else condition evaluation
            chain_steps = result.get("steps", [])
            if chain_steps:
                last_output = chain_steps[-1].get("stdout", "") or last_output
        elif ntype == "parallel":
            _run_parallel_node(db, exec_id, node, agent_paw, step_logs)
        elif ntype == "if_else":
            contains = (node.get("contains") or "").lower().strip()
            matched = contains != "" and contains in last_output.lower()
            branch_taken = "if" if matched else "else"
            step_logs.append({
                "node_id":             node.get("id", ""),
                "type":                "if_else",
                "contains":            contains,
                "matched":             matched,
                "branch_taken":        branch_taken,
                "last_output_snippet": last_output[:200],
            })
            _update_campaign_logs(db, exec_id, step_logs)
            branch_nodes = node.get("if_nodes", []) if matched else node.get("else_nodes", [])
            last_output = _walk_campaign_nodes(db, exec_id, branch_nodes, agent_paw, step_logs, last_output)
    return last_output


def _run_chain_step(node: dict, agent_paw: str) -> dict:
    """Execute a single chain node synchronously. Returns step result dict."""
    chain_id   = node.get("chain_id")
    chain_name = node.get("chain_name", "")
    node_id    = node.get("id", "")

    if not chain_id:
        return {
            "node_id": node_id, "type": "chain", "chain_name": chain_name,
            "state": "failed", "error": "No chain_id in node", "steps": [],
        }

    chain_exec_id     = None
    chain_flow_nodes  = []
    chain_actual_name = chain_name

    db = SessionLocal()
    try:
        chain = db.query(Chain).filter(Chain.id == chain_id).first()
        if not chain:
            db.close()
            return {
                "node_id": node_id, "type": "chain", "chain_name": chain_name,
                "state": "failed", "error": f"Chain not found: {chain_id}", "steps": [],
            }

        try:
            flow = json.loads(chain.flow_json or '{"nodes":[]}')
            chain_flow_nodes = flow.get("nodes", [])
        except Exception:
            pass

        if not chain_flow_nodes:
            db.close()
            return {
                "node_id": node_id, "type": "chain", "chain_name": chain.name,
                "state": "failed", "error": "Chain has no nodes", "steps": [],
            }

        agent = db.query(Agent).filter(Agent.paw == agent_paw).first()
        chain_actual_name = chain.name
        chain_exec_id = str(uuid.uuid4())
        ce = ChainExecution(
            id=chain_exec_id,
            chain_id=chain.id,
            chain_name=chain.name,
            agent_id=agent.id if agent else None,
            agent_paw=agent_paw,
            agent_hostname=agent.hostname if agent else agent_paw,
            state="running",
            flow_snapshot=chain.flow_json,
            step_logs="[]",
        )
        db.add(ce)
        db.commit()
    finally:
        db.close()

    if not chain_exec_id:
        return {
            "node_id": node_id, "type": "chain", "chain_name": chain_actual_name,
            "state": "failed", "error": "Setup failed", "steps": [],
        }

    # Run chain synchronously (blocking — we are already in a background thread)
    _run_chain_fn(chain_exec_id, chain_flow_nodes, agent_paw, chain_actual_name)

    # Read result via a fresh session
    db2 = SessionLocal()
    try:
        ce2 = db2.query(ChainExecution).filter(ChainExecution.id == chain_exec_id).first()
        inner_steps = json.loads(ce2.step_logs or "[]") if ce2 else []
        state = ce2.state if ce2 else "unknown"
    finally:
        db2.close()

    return {
        "node_id":       node_id,
        "type":          "chain",
        "chain_id":      chain_id,
        "chain_name":    chain_actual_name,
        "chain_exec_id": chain_exec_id,
        "state":         state,
        "steps":         inner_steps,
    }


def _run_parallel_node(db, exec_id: str, node: dict, agent_paw: str, step_logs: list):
    """Execute a parallel node: run all branches concurrently, wait for all."""
    node_id  = node.get("id", "")
    branches = node.get("branches", [])

    parallel_entry = {
        "node_id":  node_id,
        "type":     "parallel",
        "state":    "running",
        "branches": [],
    }
    idx_in_logs = len(step_logs)
    step_logs.append(parallel_entry)
    _update_campaign_logs(db, exec_id, step_logs)

    branch_results: list = [None] * len(branches)

    def run_branch(branch_idx: int, branch_nodes: list):
        b_logs = []
        try:
            for bnode in branch_nodes:
                if bnode.get("type") == "chain":
                    result = _run_chain_step(bnode, agent_paw)
                    b_logs.append(result)
            branch_results[branch_idx] = {
                "branch_index": branch_idx,
                "state":        "completed",
                "steps":        b_logs,
            }
        except Exception as exc:
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
    _update_campaign_logs(db, exec_id, step_logs)
