"""Per-agent wake events for long-polling.

When a console session is created or a job is enqueued for a PAW,
poll_wake.wake(paw) is called so any waiting long-poll loop returns
immediately rather than sleeping through the full hold period.
"""

import asyncio
import logging
from typing import Dict

log = logging.getLogger("morgana.core.poll_wake")

# paw -> asyncio.Event (lazy created on first access)
_events: Dict[str, asyncio.Event] = {}


def get_or_create(paw: str) -> asyncio.Event:
    """Return (creating if needed) the wake event for a PAW."""
    if paw not in _events:
        _events[paw] = asyncio.Event()
    return _events[paw]


def wake(paw: str) -> None:
    """Signal that work is waiting for this agent - wakes a long-polling loop."""
    evt = _events.get(paw)
    if evt:
        evt.set()
        log.debug("[WAKE] Signaled agent %s", paw)


def clear(paw: str) -> None:
    """Reset the wake event for this agent."""
    evt = _events.get(paw)
    if evt:
        evt.clear()
