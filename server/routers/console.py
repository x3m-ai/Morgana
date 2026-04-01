"""WebSocket console broker + native console launcher.

Browser side:  WS /api/v2/console/ws/{paw}?key={api_key}
Agent side:    WS /api/v2/console/agent/{paw}   (Authorization: Bearer {token})
Native launch: POST /api/v2/console/native/{paw}?key={api_key}
               -> spawns a real cmd.exe/bash window on the server machine
                  bridged to the agent via local_console_bridge.py
"""

import asyncio
import hashlib
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from config import settings
from core import console_sessions
from database import get_db
from models.agent import Agent

log = logging.getLogger("morgana.console")
router = APIRouter()

_BRIDGE_SCRIPT = Path(__file__).parent.parent / "core" / "local_console_bridge.py"


# ---------------------------------------------------------------------------
# Reset / cleanup endpoint
# ---------------------------------------------------------------------------

@router.delete("/session/{paw}")
async def reset_session(
    paw: str,
    key: str = Query(default=""),
):
    """Force-close any active or pending console session for this agent.

    Called by the UI Reset button to clean up a stale session before
    opening a fresh console.
    """
    if key != settings.api_key:
        raise HTTPException(status_code=403, detail="Unauthorized")

    sess = console_sessions.get(paw)
    if sess:
        # Signal done so coroutines waiting on done.wait() unblock
        sess.done.set()
        # Explicitly close WebSocket connections to speed up cleanup
        for ws_attr in ("browser_ws", "agent_ws"):
            ws = getattr(sess, ws_attr, None)
            if ws is not None:
                try:
                    await ws.send_text("\r\n[CONSOLE] Session reset by operator.\r\n")
                    await ws.close()
                except Exception:
                    pass
        console_sessions.remove(paw)
        log.info("[CONSOLE] Session force-reset for agent %s", paw)
        return {"ok": True, "paw": paw, "action": "reset"}

    return {"ok": True, "paw": paw, "action": "no_session"}


# ---------------------------------------------------------------------------
# Native console (opens real cmd.exe / bash window on operator machine)
# ---------------------------------------------------------------------------

@router.post("/native/{paw}")
async def open_native_console(
    paw: str,
    key: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Spawn a real terminal window on the server machine connected to this agent.

    The server launches local_console_bridge.py in a new cmd.exe window.
    The bridge connects to /api/v2/console/ws/{paw} as a WebSocket client and
    relays raw stdin/stdout, giving the operator a true interactive shell.
    """
    if key != settings.api_key:
        raise HTTPException(status_code=403, detail="Unauthorized")

    # Reset any stale session first
    existing = console_sessions.get(paw)
    if existing:
        existing.done.set()
        await asyncio.sleep(0.05)
        console_sessions.remove(paw)

    # Create new session - wakes the agent's long-poll immediately
    console_sessions.create(paw)

    ag = db.query(Agent).filter(Agent.paw == paw).first()
    hostname = (ag.hostname if ag else None) or paw

    ws_url = f"wss://localhost:{settings.port}/api/v2/console/ws/{paw}?key={settings.api_key}"
    python = sys.executable
    bridge = str(_BRIDGE_SCRIPT)

    if sys.platform == "win32":
        # Spawn Python directly in a new console window.
        # Avoids all cmd.exe /k quoting issues with URLs containing ?key=...
        # The bridge script sets its own window title via os.system('title ...').
        subprocess.Popen(
            [python, str(bridge), ws_url, hostname],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    else:
        # Linux/macOS - try common terminal emulators
        for term in ("gnome-terminal", "xterm", "konsole"):
            try:
                subprocess.Popen(
                    [term, "--", python, bridge, ws_url, hostname],
                    start_new_session=True,
                )
                break
            except FileNotFoundError:
                continue

    log.info("[CONSOLE] Native terminal launched for agent %s (%s)", paw, hostname)
    return {"ok": True, "paw": paw, "hostname": hostname}

@router.websocket("/ws/{paw}")
async def browser_connect(
    websocket: WebSocket,
    paw: str,
    key: str = Query(default=""),
):
    """Browser connects here to start an interactive console session."""
    # Auth via query param (browser WebSocket API cannot send custom headers)
    if key != settings.api_key:
        await websocket.close(1008, "Unauthorized")
        return

    await websocket.accept()
    log.info("[CONSOLE] Browser connected for agent %s", paw)

    sess = console_sessions.create(paw)
    sess.browser_ws = websocket

    try:
        await websocket.send_text("\r\n[CONSOLE] Waiting for agent to connect...\r\n")

        # Wait for agent to dial in (max 30 s)
        try:
            await asyncio.wait_for(sess.agent_ready.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            await websocket.send_text(
                "\r\n[ERROR] Agent did not connect within 30 s. "
                "Make sure the agent service is running.\r\n"
            )
            return

        await websocket.send_text(
            "\r\n[CONSOLE] Agent connected. Shell ready. "
            "Working directory: C:\\merlino (Windows) / /merlino (Linux)\r\n\r\n"
        )

        # ---- Bridge tasks -----------------------------------------------

        async def browser_to_agent() -> None:
            """Forward browser keystrokes to the agent shell."""
            try:
                while True:
                    data = await websocket.receive_text()
                    if sess.agent_ws:
                        await sess.agent_ws.send_text(data)
            except (WebSocketDisconnect, RuntimeError):
                pass
            except Exception as exc:
                log.debug("[CONSOLE] browser_to_agent error: %s", exc)

        async def agent_to_browser() -> None:
            """Forward agent shell output to the browser."""
            try:
                while True:
                    data = await sess.agent_ws.receive_text()
                    await websocket.send_text(data)
            except (WebSocketDisconnect, RuntimeError):
                pass
            except Exception as exc:
                log.debug("[CONSOLE] agent_to_browser error: %s", exc)

        await asyncio.gather(browser_to_agent(), agent_to_browser(), return_exceptions=True)

    finally:
        sess.done.set()
        console_sessions.remove(paw)
        log.info("[CONSOLE] Browser session closed for agent %s", paw)


# ---------------------------------------------------------------------------
# Agent endpoint
# ---------------------------------------------------------------------------

@router.websocket("/agent/{paw}")
async def agent_connect(websocket: WebSocket, paw: str):
    """Agent dials back here after receiving console_paw in a poll response."""
    # Auth via Authorization header (gorilla/websocket supports headers in Dial)
    auth = websocket.headers.get("authorization", "")
    token = auth.replace("Bearer ", "").strip()

    # Look up agent to verify token
    # We do a quick synchronous DB check via a new session
    from database import SessionLocal
    db: Session = SessionLocal()
    try:
        ag = db.query(Agent).filter(Agent.paw == paw).first()
        if ag and ag.token_hash:
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            if ag.token_hash != token_hash:
                await websocket.close(1008, "Unauthorized")
                return
    finally:
        db.close()

    sess = console_sessions.get(paw)
    if not sess:
        log.warning("[CONSOLE] No pending browser session for agent %s", paw)
        await websocket.close(1011, "No pending session")
        return

    await websocket.accept()
    sess.agent_ws = websocket
    sess.agent_ready.set()
    log.info("[CONSOLE] Agent connected for %s, bridging", paw)

    # Keep agent WS alive until browser disconnects
    try:
        await sess.done.wait()
    except Exception:
        pass
    finally:
        log.info("[CONSOLE] Agent WS closed for %s", paw)
