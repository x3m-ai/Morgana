"""
Merlino router: POST /api/v2/merlino/synchronize_morgana

Syncs the Merlino Tests table with Morgana Chains:
1. Receive list of {name, tcode, id} rows from the Merlino Tests table.
2. For each unique (name, tcode): ensure a Chain named "{name} {tcode}" exists.
   - If missing: create it and build a sequential flow from all Scripts for that TCode.
3. For each row: find the latest ChainExecution (or the specific one if ID is supplied).
4. Return enriched rows with execution data ready to write back to the Tests table.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.chain import Chain
from models.chain_execution import ChainExecution
from models.script import Script

log = logging.getLogger("morgana.router.synchronize_morgana")

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class MerlinoTestRow(BaseModel):
    name: str = ""
    tcode: str = ""
    id: Optional[str] = ""   # ChainExecution ID when already linked


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def _require_api_key(key: Optional[str] = Header(None, alias="KEY")) -> None:
    if key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_chain_flow(scripts: list) -> dict:
    """Build a sequential flow JSON dict from a list of Script ORM objects."""
    nodes = []
    for i, script in enumerate(scripts):
        nodes.append({
            "id":          str(uuid.uuid4()),
            "type":        "script",
            "script_id":   script.id,
            "script_name": script.name or "",
            "tcode":       script.tcode or "",
            "executor":    script.executor or "powershell",
            "order":       i,
            "branches":    [],
        })
    return {"nodes": nodes}


def _format_duration(started_at, finished_at) -> str:
    if not started_at or not finished_at:
        return ""
    try:
        delta = finished_at - started_at
        ms = int(delta.total_seconds() * 1000)
        if ms < 1000:
            return f"{ms} ms"
        s = delta.total_seconds()
        if s < 60:
            return f"{s:.1f} s"
        m = int(s // 60)
        sr = int(s % 60)
        return f"{m}m {sr}s"
    except Exception:
        return ""


def _format_agent(exec_rec: ChainExecution) -> str:
    parts = []
    if exec_rec.agent_hostname:
        parts.append(exec_rec.agent_hostname)
    if exec_rec.agent_paw:
        parts.append(f"[{exec_rec.agent_paw}]")
    return " ".join(parts)


def _extract_stdout(exec_rec: ChainExecution) -> str:
    """Concatenate stdout from step_logs (truncated to 2000 chars)."""
    try:
        steps = json.loads(exec_rec.step_logs or "[]")
        parts = []
        for step in steps:
            out = step.get("stdout") or step.get("output") or ""
            if out:
                parts.append(str(out).strip())
        return "\n".join(parts)[:2000]
    except Exception:
        return ""


def _exit_code_from_steps(step_logs_json: str, state: str) -> int:
    """Return 0 (success) or 1 (error) based on step_logs and execution state."""
    try:
        steps = json.loads(step_logs_json or "[]")
        for step in steps:
            code = step.get("exit_code")
            if code is not None and str(code) not in ("0", ""):
                return 1
            if step.get("state") in ("failed", "FAILED", "error"):
                return 1
    except Exception:
        pass
    return 0 if state in ("completed", "FINISHED") else 1


def _map_state(raw_state: str) -> str:
    if not raw_state:
        return ""
    s = raw_state.upper()
    return "FINISHED" if s == "COMPLETED" else s


def _fmt_dt(dt) -> str:
    if not dt:
        return ""
    return dt.strftime("%m/%d/%y %I:%M:%S %p")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/synchronize_morgana")
def synchronize_morgana(
    payload: List[MerlinoTestRow],
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    """
    Sync Merlino Tests table with Morgana Chains.
    Creates chains where missing, then returns enriched rows with the latest
    execution data so Merlino can update the Tests table in-place.
    """
    created_chains = 0
    rows_out = []

    for row in payload:
        name = (row.name or "").strip()
        tcode = (row.tcode or "").strip().upper()
        existing_exec_id = (row.id or "").strip()

        if not name or not tcode:
            continue

        chain_name = f"{name} {tcode}"

        # --- Ensure chain exists ---
        chain = db.query(Chain).filter(Chain.name == chain_name).first()
        if chain is None:
            scripts = (
                db.query(Script)
                .filter(Script.tcode == tcode)
                .order_by(Script.name)
                .all()
            )
            flow = _build_chain_flow(scripts)
            chain = Chain(
                id=str(uuid.uuid4()),
                name=chain_name,
                description=f"Auto-created from Merlino sync. TCode: {tcode}",
                flow_json=json.dumps(flow),
                tcode_coverage=tcode,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(chain)
            db.flush()
            created_chains += 1
            log.info(
                "[SYNC_MORGANA] Created chain: %s (scripts=%d)",
                chain_name,
                len(scripts),
            )

        # --- Find the relevant execution ---
        exec_rec = None
        if existing_exec_id:
            exec_rec = (
                db.query(ChainExecution)
                .filter(ChainExecution.id == existing_exec_id)
                .first()
            )
        if exec_rec is None:
            exec_rec = (
                db.query(ChainExecution)
                .filter(ChainExecution.chain_id == chain.id)
                .order_by(ChainExecution.started_at.desc())
                .first()
            )

        # --- Build output row ---
        if exec_rec:
            state_out = _map_state(exec_rec.state or "")
            exit_code = _exit_code_from_steps(exec_rec.step_logs or "", exec_rec.state or "")
            agent_str = _format_agent(exec_rec)
            duration_str = _format_duration(exec_rec.started_at, exec_rec.finished_at)
            description = (
                f"Chain: {chain.name} | Agent: {agent_str} | "
                f"Duration: {duration_str} | State: {state_out}"
            )
            rows_out.append({
                "name":        name,
                "tcode":       tcode,
                "chain_id":    chain.id,
                "chain_name":  chain.name,
                "exit_code":   exit_code,
                "state":       state_out,
                "date":        _fmt_dt(exec_rec.started_at),
                "type":        "Chain",
                "agent":       agent_str,
                "duration":    duration_str,
                "created":     _fmt_dt(exec_rec.started_at),
                "finished":    _fmt_dt(exec_rec.finished_at),
                "stdout":      _extract_stdout(exec_rec),
                "id":          exec_rec.id,
                "description": description,
            })
        else:
            # Chain exists (or just created) but no execution yet
            rows_out.append({
                "name":        name,
                "tcode":       tcode,
                "chain_id":    chain.id,
                "chain_name":  chain.name,
                "exit_code":   "",
                "state":       "",
                "date":        "",
                "type":        "Chain",
                "agent":       "",
                "duration":    "",
                "created":     "",
                "finished":    "",
                "stdout":      "",
                "id":          "",
                "description": f"Chain: {chain.name} | Ready for execution.",
            })

    db.commit()
    log.info(
        "[SYNC_MORGANA] Done: created_chains=%d synced_rows=%d",
        created_chains,
        len(rows_out),
    )
    return {
        "created_chains": created_chains,
        "synced_rows":    len(rows_out),
        "rows":           rows_out,
    }
