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
from core.auth import verify_key_value, require_api_key
from database import get_db, SessionLocal
from models.agent import Agent

log = logging.getLogger("morgana.console")
router = APIRouter()


# ---------------------------------------------------------------------------
# Reset / cleanup endpoint
# ---------------------------------------------------------------------------

@router.delete("/session/{paw}")
async def reset_session(
    paw: str,
    db: Session = Depends(get_db),
    _auth: str = Depends(require_api_key),
):
    """Force-close any active or pending console session for this agent.

    Called by the UI Reset button to clean up a stale session before
    opening a fresh console.
    """

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
        addr = writer.get_extra_info("peername")
        log.info("[CONSOLE] TCP relay: client connected from %s (port %d)", addr, port)
        try:
            async with websockets.connect(ws_url, ssl=ssl_ctx) as ws:
                log.info("[CONSOLE] TCP relay: WS connected to %s", ws_url.split("?")[0])

                async def tcp_to_ws():
                    total = 0
                    while True:
                        data = await reader.read(4096)
                        if not data:
                            log.info("[CONSOLE] TCP relay: tcp_to_ws EOF (sent %d bytes total)", total)
                            break
                        total += len(data)
                        log.info("[CONSOLE] TCP relay: TCP->WS %d bytes (total=%d)", len(data), total)
                        await ws.send(data.decode("utf-8", errors="replace"))

                async def ws_to_tcp():
                    total = 0
                    async for msg in ws:
                        b = msg.encode("utf-8") if isinstance(msg, str) else msg
                        total += len(b)
                        log.info("[CONSOLE] TCP relay: WS->TCP %d bytes (total=%d)", len(b), total)
                        writer.write(b)
                        await writer.drain()
                    log.info("[CONSOLE] TCP relay: ws_to_tcp WS closed (sent %d bytes total)", total)

                done, pending = await asyncio.wait(
                    [asyncio.ensure_future(tcp_to_ws()),
                     asyncio.ensure_future(ws_to_tcp())],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                log.info("[CONSOLE] TCP relay: bridge ended for port %d", port)
        except Exception as exc:
            log.warning("[CONSOLE] TCP relay error: %s", exc)
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


def _spawn_in_user_session(script_path: str) -> int:
    """Launch a PowerShell script in the active interactive user session.

    When Morgana runs as an NT Service (Session 0), subprocess.Popen creates
    a process in Session 0 which is invisible to the logged-in user.
    This function uses WTSQueryUserToken + CreateProcessAsUserW to spawn the
    process directly in the active user's desktop session (Session 1+).

    Falls back to subprocess.Popen if WTSQueryUserToken fails (e.g. running
    interactively outside of a service context).

    Returns the spawned process PID.
    """
    import ctypes
    import ctypes.wintypes as W

    kernel32 = ctypes.windll.kernel32
    wtsapi32 = ctypes.windll.wtsapi32
    advapi32 = ctypes.windll.advapi32
    userenv  = ctypes.windll.userenv

    session_id = kernel32.WTSGetActiveConsoleSessionId()

    hToken = W.HANDLE()
    if not wtsapi32.WTSQueryUserToken(session_id, ctypes.byref(hToken)):
        err = kernel32.GetLastError()
        log.warning("[CONSOLE] WTSQueryUserToken failed (err=%d), using Popen fallback", err)
        proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return proc.pid

    lpEnv = ctypes.c_void_p()
    userenv.CreateEnvironmentBlock(ctypes.byref(lpEnv), hToken, False)

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb",              W.DWORD),
            ("lpReserved",      W.LPWSTR),
            ("lpDesktop",       W.LPWSTR),
            ("lpTitle",         W.LPWSTR),
            ("dwX",             W.DWORD), ("dwY",             W.DWORD),
            ("dwXSize",         W.DWORD), ("dwYSize",         W.DWORD),
            ("dwXCountChars",   W.DWORD), ("dwYCountChars",   W.DWORD),
            ("dwFillAttribute", W.DWORD),
            ("dwFlags",         W.DWORD),
            ("wShowWindow",     W.WORD),
            ("cbReserved2",     W.WORD),
            ("lpReserved2",     ctypes.c_void_p),
            ("hStdInput",  W.HANDLE),
            ("hStdOutput", W.HANDLE),
            ("hStdError",  W.HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess",    W.HANDLE),
            ("hThread",     W.HANDLE),
            ("dwProcessId", W.DWORD),
            ("dwThreadId",  W.DWORD),
        ]

    si = STARTUPINFOW()
    si.cb        = ctypes.sizeof(si)
    si.lpDesktop = "winsta0\\default"
    pi = PROCESS_INFORMATION()

    CREATE_NEW_CONSOLE        = 0x00000010
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    NORMAL_PRIORITY_CLASS     = 0x00000020

    cmd_line = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{script_path}"'

    ok = advapi32.CreateProcessAsUserW(
        hToken,
        None,
        cmd_line,
        None, None,
        False,
        NORMAL_PRIORITY_CLASS | CREATE_NEW_CONSOLE | CREATE_UNICODE_ENVIRONMENT,
        lpEnv,
        None,
        ctypes.byref(si),
        ctypes.byref(pi),
    )

    pid = pi.dwProcessId if ok else -1

    if ok:
        kernel32.CloseHandle(pi.hProcess)
        kernel32.CloseHandle(pi.hThread)
    if lpEnv:
        userenv.DestroyEnvironmentBlock(lpEnv)
    kernel32.CloseHandle(hToken)

    if not ok:
        err = kernel32.GetLastError()
        log.warning("[CONSOLE] CreateProcessAsUserW failed (err=%d), using Popen fallback", err)
        proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return proc.pid

    log.info("[CONSOLE] Spawned PowerShell in user session %d, PID=%d", session_id, pid)
    return pid




@router.post("/native/{paw}")
async def open_native_console(
    paw: str,
    db: Session = Depends(get_db),
    _auth: str = Depends(require_api_key),
):
    """Spawn a real PowerShell terminal window connected to this agent.

    Architecture:
      1. Server creates a TCP relay on a random localhost port.
      2. The TCP relay bridges the PowerShell window to /ws/{paw}.
      3. PowerShell uses Console.ReadKey($true) for raw input - bulletproof.
    """

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
    ws_url = f"wss://localhost:{settings.port}/api/v2/console/ws/{paw}?key={settings.api_key}"
    await _tcp_relay(port, ws_url)

    if sys.platform == "win32":
        # PowerShell script: TCP connect + Console.ReadKey($true) for keyboard
        log_path = tempfile.gettempdir() + "\\morgana-console.log"
        ps_script = textwrap.dedent(f"""\
            $host.UI.RawUI.WindowTitle = 'Morgana - {hostname}'
            $script:logFile = '{log_path}'
            function Write-Log {{
                param([string]$msg)
                $ts = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')
                $line = "$ts $msg"
                Add-Content -Path $script:logFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
                Write-Host $line
            }}
            try {{
            Write-Log '[START] Morgana console connecting to TCP relay on port {port}'
            # Intercept Ctrl+C so it goes to the remote shell, not kills this script
            [System.Console]::TreatControlCAsInput = $true
            $tcp = New-Object System.Net.Sockets.TcpClient
            try {{
                $tcp.Connect('127.0.0.1', {port})
            }} catch {{
                Write-Log "[ERROR] TCP connect failed on port {port}: $_"
                Write-Host ''
                Write-Host 'Press any key to close...'
                $null = $host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
                exit 1
            }}
            Write-Log '[OK] TCP connected to relay port {port}'
            $stream = $tcp.GetStream()
            $enc = [System.Text.Encoding]::UTF8

            # Recv thread (server output -> console)
            # Simple blocking read: cmd.exe sends its own prompts and echo,
            # so we just display whatever arrives without adding anything.
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
            # cmd.exe with piped stdin does NOT echo keystrokes, so we must
            # echo printable chars locally.  But cmd.exe DOES send its own
            # prompt (C:\merlino>) via stdout, so we must NOT add a fake one.
            try {{
                while ($true) {{
                    $key = [System.Console]::ReadKey($true)
                    $bytes = $null
                    if ($key.Key -eq [System.ConsoleKey]::Enter) {{
                        [System.Console]::WriteLine()
                        $bytes = $enc.GetBytes("`r`n")
                    }} elseif ($key.Key -eq [System.ConsoleKey]::Backspace) {{
                        [System.Console]::Write("`b `b")
                        $bytes = $enc.GetBytes("`b")
                    }} elseif ($key.KeyChar -ne [char]0) {{
                        if ($key.Modifiers -band [System.ConsoleModifiers]::Control) {{
                            # Ctrl+letter -> control code (Ctrl+C = 0x03, etc.)
                            $bytes = [byte[]]@(($key.Key - [System.ConsoleKey]::A + 1))
                        }} else {{
                            # Printable character: local echo + send
                            [System.Console]::Write($key.KeyChar)
                            $bytes = $enc.GetBytes([string]$key.KeyChar)
                        }}
                    }} else {{
                        # Special keys: VT escape sequences
                        $vt = @{{
                            [System.ConsoleKey]::UpArrow    = "`e[A"
                            [System.ConsoleKey]::DownArrow  = "`e[B"
                            [System.ConsoleKey]::RightArrow = "`e[C"
                            [System.ConsoleKey]::LeftArrow  = "`e[D"
                            [System.ConsoleKey]::Home       = "`e[H"
                            [System.ConsoleKey]::End        = "`e[F"
                            [System.ConsoleKey]::Delete     = "`e[3~"
                        }}
                        if ($vt.ContainsKey($key.Key)) {{
                            $bytes = $enc.GetBytes($vt[$key.Key])
                        }}
                    }}
                    if ($bytes -ne $null) {{
                        $stream.Write($bytes, 0, $bytes.Length)
                        $stream.Flush()
                    }}
                }}
            }} catch {{
                Write-Log "[ERROR] Console keyboard loop exception: $_"
            }}

            $tcp.Close()
            Write-Log '[END] Console session ended'
            }} catch {{
                Write-Log "[FATAL] Unhandled exception: $_"
                Write-Host ''
                Write-Host "[FATAL] $_"
            }}
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
        log.info("[CONSOLE] PS1 temp script written to %s", tf.name)

        try:
            pid = _spawn_in_user_session(tf.name)
            log.info("[CONSOLE] PowerShell window spawned, PID=%d, port=%d", pid, port)
        except Exception as exc:
            log.error("[CONSOLE] Failed to spawn PowerShell window: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to spawn console: {exc}")

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
    db = SessionLocal()
    try:
        valid = verify_key_value(key, db)
    finally:
        db.close()
    if not valid:
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
            "\r\n[CONSOLE] Agent connected. Shell ready.\r\n"
            "[NOTE] Agent runs as NT Service (Session 0) - GUI apps (notepad, calc) "
            "launch but are invisible on the user desktop. Use CLI tools only.\r\n"
            "[TIP] Up/Down arrow = command history\r\n\r\n"
        )

        # ---- Bridge tasks -----------------------------------------------

        async def browser_to_agent() -> None:
            """Forward browser keystrokes to the agent shell."""
            log.info("[CONSOLE] browser_to_agent: start (paw=%s)", paw)
            try:
                while True:
                    data = await websocket.receive_text()
                    log.info("[CONSOLE] browser_to_agent: got %d bytes from TCP relay", len(data))
                    if sess.agent_ws:
                        await sess.agent_ws.send_text(data)
                    else:
                        log.warning("[CONSOLE] browser_to_agent: agent_ws is None, dropping data")
            except (WebSocketDisconnect, RuntimeError) as exc:
                log.info("[CONSOLE] browser_to_agent: ended (%s)", exc)
            except Exception as exc:
                log.warning("[CONSOLE] browser_to_agent error: %s", exc)

        async def agent_to_browser() -> None:
            """Forward agent shell output to the browser."""
            log.info("[CONSOLE] agent_to_browser: start (paw=%s)", paw)
            try:
                while True:
                    data = await sess.agent_ws.receive_text()
                    log.info("[CONSOLE] agent_to_browser: got %d bytes from agent", len(data))
                    await websocket.send_text(data)
            except (WebSocketDisconnect, RuntimeError) as exc:
                log.info("[CONSOLE] agent_to_browser: ended (%s)", exc)
                # Agent disconnected — notify browser
                try:
                    await websocket.send_text(
                        "\r\n[CONSOLE] Agent disconnected. Session closed.\r\n"
                    )
                except Exception:
                    pass
            except Exception as exc:
                log.warning("[CONSOLE] agent_to_browser error: %s", exc)

        async def session_timeout() -> None:
            """Safety net: kill session after 4 hours max."""
            await asyncio.sleep(4 * 3600)
            log.warning("[CONSOLE] Session TTL expired for agent %s", paw)

        # When ANY task ends (agent disconnect, browser disconnect, or TTL),
        # cancel the others so the session is cleaned up immediately.
        tasks = [
            asyncio.ensure_future(browser_to_agent()),
            asyncio.ensure_future(agent_to_browser()),
            asyncio.ensure_future(session_timeout()),
        ]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()

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

    sess = console_sessions.get(paw)
    if not sess:
        log.warning("[CONSOLE] No pending browser session for agent %s", paw)
        await websocket.close(1011, "No pending session")
        return

    await websocket.accept()
    sess.agent_ws = websocket
    sess.agent_ready.set()
    log.info("[CONSOLE] Agent connected for %s, bridging", paw)

    # Keep agent WS alive until browser disconnects or session TTL expires.
    # Also guard against infinite hang with a 4h timeout.
    try:
        await asyncio.wait_for(sess.done.wait(), timeout=4 * 3600)
    except asyncio.TimeoutError:
        log.warning("[CONSOLE] Agent session TTL expired for %s", paw)
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        log.info("[CONSOLE] Agent WS closed for %s", paw)
