#!/usr/bin/env python3
"""
Morgana Native Console Bridge
=====================================================================
Spawned by the Morgana server when the operator clicks "Console".
Connects this machine's stdin/stdout to the remote agent's cmd.exe
via the Morgana WebSocket console session.

Uses websockets.sync.client (websockets >= 12) with two plain threads:
  - recv thread: WebSocket -> stdout
  - send thread: keyboard   -> WebSocket

No asyncio - avoids executor/event-loop issues in a spawned console window.

Usage (internal - do not run manually):
    python local_console_bridge.py <ws_url> <hostname>
"""

import ssl
import sys
import os
import threading

# Set the console window title now (we are already inside the new window)
if sys.platform == "win32" and len(sys.argv) >= 3:
    _hostname = sys.argv[2]
    os.system(f"title Morgana - {_hostname}")

# ---------------------------------------------------------------------------
# Platform keyboard helpers
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    import msvcrt

    _EXTENDED_MAP = {
        "H": "\x1b[A",   # Up
        "P": "\x1b[B",   # Down
        "M": "\x1b[C",   # Right
        "K": "\x1b[D",   # Left
        "G": "\x1b[H",   # Home
        "O": "\x1b[F",   # End
        "I": "\x1b[5~",  # PgUp
        "Q": "\x1b[6~",  # PgDn
        "S": "\x1b[3~",  # Del
    }

    def _read_char() -> str:
        """Read one raw character from the Windows console (no echo, no line buffer)."""
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            return _EXTENDED_MAP.get(ch2, "")
        return ch

    def _wait_key():
        msvcrt.getwch()

else:
    import tty
    import termios

    def _read_char() -> str:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def _wait_key():
        sys.stdin.read(1)


# ---------------------------------------------------------------------------
# Bridge threads
# ---------------------------------------------------------------------------

def _recv_thread(ws, stop_event: threading.Event):
    """WebSocket -> stdout  (daemon thread)."""
    try:
        while not stop_event.is_set():
            try:
                msg = ws.recv(timeout=1.0)
            except TimeoutError:
                continue
            if isinstance(msg, bytes):
                sys.stdout.buffer.write(msg)
                sys.stdout.buffer.flush()
            else:
                sys.stdout.write(msg)
                sys.stdout.flush()
    except Exception:
        pass
    finally:
        stop_event.set()


def _send_thread(ws, stop_event: threading.Event):
    """keyboard -> WebSocket  (daemon thread)."""
    try:
        while not stop_event.is_set():
            ch = _read_char()
            if not ch:
                continue
            try:
                ws.send(ch)
            except Exception:
                break
    except Exception:
        pass
    finally:
        stop_event.set()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(ws_url: str, hostname: str):
    ssl_ctx = None
    if ws_url.startswith("wss://"):
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    print(f"\r\n[MORGANA] Connecting to {hostname}...")
    sys.stdout.flush()

    try:
        from websockets.sync.client import connect

        extra = {"ssl": ssl_ctx} if ssl_ctx else {}
        with connect(ws_url, **extra) as ws:
            stop = threading.Event()
            rt = threading.Thread(target=_recv_thread, args=(ws, stop), daemon=True)
            st = threading.Thread(target=_send_thread, args=(ws, stop), daemon=True)
            rt.start()
            st.start()
            # Block main thread until connection closes or error
            stop.wait()

    except Exception as exc:
        print(f"\r\n[ERROR] {exc}\r\n")
        sys.stdout.flush()

    print("\r\n[MORGANA] Console session closed.")
    sys.stdout.flush()
    if sys.platform == "win32":
        print("Press any key to close this window...")
        sys.stdout.flush()
        _wait_key()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: local_console_bridge.py <ws_url> <hostname>")
        sys.exit(1)
    run(sys.argv[1], sys.argv[2])

