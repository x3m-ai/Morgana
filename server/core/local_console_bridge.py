#!/usr/bin/env python3
"""
Morgana Native Console Bridge
=====================================================================
Spawned by the Morgana server when the operator clicks "Console".
Connects this machine's stdin/stdout to the remote agent's cmd.exe
via the Morgana WebSocket console session.

Usage (internal - do not run manually):
    python local_console_bridge.py <ws_url> <hostname>
"""

import asyncio
import ssl
import sys
import os
import subprocess

# Set the console window title now (we are already inside the new window)
if sys.platform == "win32" and len(sys.argv) >= 3:
    _hostname = sys.argv[2]
    os.system(f"title Morgana - {_hostname}")

# Windows raw keyboard input
if sys.platform == "win32":
    import msvcrt

    def _read_char():
        """Read one raw character from the console (no echo, no buffering)."""
        ch = msvcrt.getwch()
        # getwch returns '\x00' or '\xe0' for special keys (arrows, F-keys).
        # Read the second byte and map to VT sequences xterm understands.
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            _MAP = {
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
            return _MAP.get(ch2, "")
        return ch

else:
    import tty
    import termios

    def _read_char():
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return ch


async def _recv_loop(ws):
    """Receive data from WebSocket and write to stdout."""
    try:
        async for msg in ws:
            if isinstance(msg, bytes):
                sys.stdout.buffer.write(msg)
            else:
                sys.stdout.write(msg)
            sys.stdout.flush()
    except Exception:
        pass


async def _send_loop(ws, loop):
    """Read raw keystrokes and send to WebSocket."""
    try:
        while True:
            ch = await loop.run_in_executor(None, _read_char)
            if not ch:
                continue
            await ws.send(ch)
    except Exception:
        pass


async def run(ws_url: str, hostname: str):
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    print(f"\r\n[MORGANA] Connecting to {hostname}...")
    print("[MORGANA] Waiting for agent shell (up to 30s)...\r\n")
    sys.stdout.flush()

    try:
        import websockets
        async with websockets.connect(ws_url, ssl=ssl_ctx) as ws:
            loop = asyncio.get_event_loop()
            recv_task = asyncio.ensure_future(_recv_loop(ws))
            send_task = asyncio.ensure_future(_send_loop(ws, loop))
            done, pending = await asyncio.wait(
                [recv_task, send_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
    except Exception as exc:
        print(f"\r\n[ERROR] {exc}\r\n")

    print("\r\n[MORGANA] Console session closed.")
    if sys.platform == "win32":
        print("Press any key to close this window...")
        sys.stdout.flush()
        msvcrt.getwch()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: local_console_bridge.py <ws_url> <hostname>")
        sys.exit(1)
    asyncio.run(run(sys.argv[1], sys.argv[2]))
