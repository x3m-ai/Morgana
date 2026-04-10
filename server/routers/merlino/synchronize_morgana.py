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
import re
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from core.auth import require_api_key
from database import get_db
from models.agent import Agent
from models.chain import Chain
from models.chain_execution import ChainExecution
from models.script import Script
from models.test import Test as TestRecord

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
    _: str = Depends(require_api_key),
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

        if not name:
            continue

        # Use name as-is -- Merlino now sends names that already include the TCode
        # (e.g. "LSASS memory access via process handle T1003.001").
        # Do NOT append tcode again or the chain name would have a double TCode.
        chain_name = name

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

    # Fetch ALL Test records from Morgana (same source as the UI /api/v2/tests endpoint).
    # Tests are the individual script executions dispatched to agents.
    agents_by_id = {a.id: a for a in db.query(Agent).all()}
    all_tests = (
        db.query(TestRecord)
        .order_by(TestRecord.created_at.desc())
        .limit(2000)
        .all()
    )
    all_morgana_tests = []
    for t in all_tests:
        ag = agents_by_id.get(t.agent_id)
        ag_str = f"{ag.hostname} [{ag.paw}]" if ag else ""
        # Strip "chain:" prefix that is prepended when creating Test records in chains.py
        name = (t.operation_name or "").removeprefix("chain:").strip()
        tcode_val = t.tcode or ""
        dur = _format_duration(t.started_at, t.finished_at)
        state_out = _map_state(t.state or "")
        exit_code = t.exit_code if t.exit_code is not None else ""
        all_morgana_tests.append({
            "name":        name,
            "tcode":       tcode_val,
            "id":          t.id,
            "state":       state_out,
            "exit_code":   exit_code,
            "date":        _fmt_dt(t.started_at or t.created_at),
            "type":        "Test",
            "agent":       ag_str,
            "duration":    dur,
            "created":     _fmt_dt(t.started_at),
            "finished":    _fmt_dt(t.finished_at),
            "stdout":      (t.stdout or "")[:500],
            "description": (
                f"Test: {name} | Agent: {ag_str} | "
                f"Duration: {dur} | State: {state_out}"
            ),
        })

    log.info(
        "[SYNC_MORGANA] Done: created_chains=%d synced_rows=%d all_tests=%d",
        created_chains,
        len(rows_out),
        len(all_morgana_tests),
    )
    return {
        "created_chains":    created_chains,
        "synced_rows":       len(rows_out),
        "rows":              rows_out,
        "all_morgana_tests": all_morgana_tests,
    }
