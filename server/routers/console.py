"""WebSocket console broker.

Browser side:  WS /api/v2/console/ws/{paw}?key={api_key}
Agent side:    WS /api/v2/console/agent/{paw}   (Authorization: Bearer {token})

Flow:
  1. Browser opens /ws/{paw}  -> session created, message sent: "Waiting for agent..."
  2. Agent polls and receives console_paw in the poll response
  3. Agent opens /agent/{paw} -> session bridged, full bidirectional traffic
  4. When either side disconnects, both sides are cleaned up
"""

import asyncio
import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from config import settings
from core import console_sessions
from database import get_db
from models.agent import Agent
from fastapi import Depends

log = logging.getLogger("morgana.console")
router = APIRouter()


# ---------------------------------------------------------------------------
# Browser endpoint
# ---------------------------------------------------------------------------

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
