"""WebSocket console broker + native console launcher.

Browser side:  WS /api/v2/console/ws/{paw}?key={api_key}
Agent side:    WS /api/v2/console/agent/{paw}   (Authorization: Bearer {token})
Native launch: POST /api/v2/console/native/{paw}?key={api_key}
               -> opens a TCP relay on localhost, then spawns a PowerShell
                  window that connects TCP and uses Console.ReadKey($true)
                  for bulletproof raw keyboard input.
"""

import asyncio
import hashlib
import logging
import socket
import subprocess
import sys
import tempfile
import textwrap
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
# TCP relay: bridges one TCP socket to the WS console broker (/ws/{paw})
# ---------------------------------------------------------------------------

def _free_port() -> int:
    """Pick a random free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _tcp_relay(port: int, ws_url: str) -> None:
    """Accept one TCP connection and bridge it bidirectionally to ws_url."""
    import ssl as _ssl
    import websockets

    ssl_ctx = None
    if ws_url.startswith("wss://"):
        ssl_ctx = _ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = _ssl.CERT_NONE

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            async with websockets.connect(ws_url, ssl=ssl_ctx) as ws:

                async def tcp_to_ws():
                    while True:
                        data = await reader.read(4096)
                        if not data:
                            break
                        await ws.send(data.decode("utf-8", errors="replace"))

                async def ws_to_tcp():
                    async for msg in ws:
                        b = msg.encode("utf-8") if isinstance(msg, str) else msg
                        writer.write(b)
                        await writer.drain()

                done, pending = await asyncio.wait(
                    [asyncio.ensure_future(tcp_to_ws()),
                     asyncio.ensure_future(ws_to_tcp())],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
        except Exception as exc:
            log.debug("[CONSOLE] TCP relay error: %s", exc)
        finally:
            try:
                writer.close()
            except Exception:
                pass

    server = await asyncio.start_server(_handle, "127.0.0.1", port)
    log.info("[CONSOLE] TCP relay listening on 127.0.0.1:%d", port)
    asyncio.ensure_future(_relay_lifetime(server))


async def _relay_lifetime(server: asyncio.Server) -> None:
    """Close the TCP relay server after 10 minutes (safety cleanup)."""
    await asyncio.sleep(600)
    server.close()
    log.debug("[CONSOLE] TCP relay expired and closed")


# ---------------------------------------------------------------------------
# Native console (opens real PowerShell window on operator machine)
# ---------------------------------------------------------------------------

@router.post("/native/{paw}")
async def open_native_console(
    paw: str,
    key: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Spawn a real PowerShell terminal window connected to this agent.

    Architecture:
      1. Server creates a TCP relay on a random localhost port.
      2. The TCP relay bridges the PowerShell window to /ws/{paw}.
      3. PowerShell uses Console.ReadKey($true) for raw input - bulletproof.
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

    # Start TCP relay
    port = _free_port()
    ws_scheme = "wss" if settings.ssl_enabled else "ws"
    ws_url = f"{ws_scheme}://localhost:{settings.port}/api/v2/console/ws/{paw}?key={settings.api_key}"
    await _tcp_relay(port, ws_url)

    if sys.platform == "win32":
        # PowerShell script: TCP connect + Console.ReadKey($true) for keyboard
        ps_script = textwrap.dedent(f"""\
            $host.UI.RawUI.WindowTitle = 'Morgana - {hostname}'
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect('127.0.0.1', {port})
            $stream = $tcp.GetStream()
            $enc = [System.Text.Encoding]::UTF8

            # Recv thread (server output -> console)
            $iss = [System.Management.Automation.Runspaces.InitialSessionState]::CreateDefault()
            $rs  = [System.Management.Automation.Runspaces.RunspaceFactory]::CreateRunspace($iss)
            $rs.Open()
            $rs.SessionStateProxy.SetVariable('stream', $stream)
            $rs.SessionStateProxy.SetVariable('enc', $enc)
            $ps2 = [System.Management.Automation.PowerShell]::Create()
            $ps2.Runspace = $rs
            [void]$ps2.AddScript({{
                $buf = New-Object byte[] 4096
                while ($true) {{
                    try {{
                        $n = $stream.Read($buf, 0, 4096)
                        if ($n -le 0) {{ break }}
                        [System.Console]::Write($enc.GetString($buf, 0, $n))
                    }} catch {{ break }}
                }}
            }})
            [void]$ps2.BeginInvoke()

            # Main thread: raw keyboard -> TCP
            try {{
                while ($true) {{
                    $key = [System.Console]::ReadKey($true)
                    if ($key.Key -eq [System.ConsoleKey]::Enter) {{
                        $bytes = $enc.GetBytes("`r`n")
                    }} else {{
                        $bytes = $enc.GetBytes([string]$key.KeyChar)
                    }}
                    $stream.Write($bytes, 0, $bytes.Length)
                    $stream.Flush()
                }}
            }} catch {{}}

            $tcp.Close()
            Write-Host ''
            Write-Host '[MORGANA] Session closed. Press Enter to close...'
            Read-Host
        """)

        # Write to temp file (deleted on next OS reboot automatically)
        tf = tempfile.NamedTemporaryFile(
            suffix=".ps1", delete=False, mode="w", encoding="utf-8",
            dir=tempfile.gettempdir()
        )
        tf.write(ps_script)
        tf.close()

        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tf.name],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )

    else:
        # Linux/macOS: Python bridge fallback (Console.ReadKey not available)
        bridge = Path(__file__).parent.parent / "core" / "local_console_bridge.py"
        for term in ("gnome-terminal", "xterm", "konsole"):
            try:
                subprocess.Popen(
                    [term, "--", sys.executable, str(bridge), ws_url, hostname],
                    start_new_session=True,
                )
                break
            except FileNotFoundError:
                continue

    log.info("[CONSOLE] Native terminal launched for agent %s (%s) on TCP port %d", paw, hostname, port)
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

    # Use get_or_create so we don't blow away a session that open_native_console
    # already created (the agent may have already connected to it).
    sess = console_sessions.get_or_create(paw)
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
