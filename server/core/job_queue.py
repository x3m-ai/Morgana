"""
In-memory job queue.
Maps agent PAW -> deque of pending job IDs.
Thread-safe for single-process FastAPI (not distributed).
For multi-process deployments, replace with Redis.
"""

import logging
from collections import deque
from threading import Lock
from typing import Optional

log = logging.getLogger("morgana.core.job_queue")


class JobQueue:
    def __init__(self):
        self._queues: dict[str, deque] = {}
        self._lock = Lock()

    def enqueue(self, paw: str, job_id: str):
        with self._lock:
            if paw not in self._queues:
                self._queues[paw] = deque()
            self._queues[paw].append(job_id)
            log.debug("[QUEUE] Enqueued job %s for agent %s (queue size: %d)", job_id, paw, len(self._queues[paw]))

    def dequeue(self, paw: str) -> Optional[str]:
        with self._lock:
            q = self._queues.get(paw)
            if q:
                job_id = q.popleft()
                log.debug("[QUEUE] Dequeued job %s for agent %s", job_id, paw)
                return job_id
            return None

    def peek(self, paw: str) -> Optional[str]:
        with self._lock:
            q = self._queues.get(paw)
            return q[0] if q else None

    def pending_count(self, paw: str) -> int:
        with self._lock:
            return len(self._queues.get(paw, []))

    def all_counts(self) -> dict:
        with self._lock:
            return {paw: len(q) for paw, q in self._queues.items()}


# Singleton instance
job_queue = JobQueue()
