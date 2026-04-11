"""In-process progress registry for in-flight conversions.

Partners watching the progress page need row-level feedback, but the
worker synchronously runs `run_conversion` inside `asyncio.to_thread`
and returns once the whole job is done — the web layer can't see what
the converter is doing mid-run.

This module holds an in-memory dict keyed by job_id that the
converter populates via the BaseConverter progress callback, and a
dedicated route exposes it so the web layer can merge it into its
existing /api/jobs/[id] polling response. See UX_REVIEW.md §3.6.

Same design pattern as cancellation.py — thread-safe because the
converter writes from a worker thread while the FastAPI event loop
reads from the HTTP handler. Single-worker deployment only; a
multi-worker setup would need Redis.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, asdict


@dataclass
class ProgressSnapshot:
    processed: int
    total: int
    # Unix epoch seconds when this snapshot was last updated, so the
    # web layer can compute rate-based ETAs without trusting client
    # clocks.
    updated_at: float


class ProgressRegistry:
    """Thread-safe in-memory map of job_id -> ProgressSnapshot."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._progress: dict[str, ProgressSnapshot] = {}

    def update(self, job_id: str, processed: int, total: int) -> None:
        import time

        with self._lock:
            self._progress[job_id] = ProgressSnapshot(
                processed=processed,
                total=total,
                updated_at=time.time(),
            )

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            snap = self._progress.get(job_id)
            if snap is None:
                return None
            return asdict(snap)

    def clear(self, job_id: str) -> None:
        with self._lock:
            self._progress.pop(job_id, None)


# Module-level singleton. Same single-process caveat as
# cancellation.registry.
registry = ProgressRegistry()
