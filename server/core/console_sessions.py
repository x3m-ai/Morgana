"""In-memory console session registry.

A console session is created when a browser WebSocket connects to /api/v2/console/ws/{paw}.
The session stays pending until the agent connects back to /api/v2/console/agent/{paw}.
After both sides are connected the server bridges all traffic bidirectionally.
"""

import asyncio
import logging
from typing import Dict, Optional

log = logging.getLogger("morgana.console.sessions")


class ConsoleSession:
    """Tracks a single browser <-> agent console session."""

    def __init__(self, paw: str) -> None:
        self.paw = paw
        self.browser_ws = None   # set by browser_connect coroutine
        self.agent_ws = None     # set by agent_connect coroutine
        # Lazy asyncio.Event creation so they are created on the running loop
        self._agent_ready: Optional[asyncio.Event] = None
        self._done: Optional[asyncio.Event] = None

    @property
    def agent_ready(self) -> asyncio.Event:
        if self._agent_ready is None:
            self._agent_ready = asyncio.Event()
        return self._agent_ready

    @property
    def done(self) -> asyncio.Event:
        if self._done is None:
            self._done = asyncio.Event()
        return self._done


# paw -> active ConsoleSession
_sessions: Dict[str, ConsoleSession] = {}


def create(paw: str) -> ConsoleSession:
    """Create (or replace) a session for the given agent paw."""
    from core import poll_wake  # local import to avoid circular
    sess = ConsoleSession(paw)
    _sessions[paw] = sess
    poll_wake.wake(paw)  # immediately unblock any waiting long-poll for this agent
    log.debug("[SESSIONS] Created session for %s", paw)
    return sess


def get_or_create(paw: str) -> ConsoleSession:
    """Return the existing session for paw (if any) or create a new one.

    Used by browser_connect so that a session pre-created by open_native_console
    is not accidentally replaced - the agent may have already connected to it.
    """
    sess = _sessions.get(paw)
    if sess is not None:
        log.debug("[SESSIONS] Reusing existing session for %s", paw)
        return sess
    return create(paw)


def get(paw: str) -> Optional[ConsoleSession]:
    return _sessions.get(paw)


def remove(paw: str) -> None:
    _sessions.pop(paw, None)
    log.debug("[SESSIONS] Removed session for %s", paw)


def pending_paw(paw: str) -> Optional[str]:
    """Return paw if a browser is waiting but agent has not yet connected."""
    sess = _sessions.get(paw)
    if sess and sess.agent_ws is None:
        return paw
    return None
