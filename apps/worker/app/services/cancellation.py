"""Cooperative cancellation registry for in-flight conversions.

The web layer is the authoritative source of truth for job state — when a
user clicks Cancel, the Next.js API route updates the database immediately
and tells this worker to drop the job. The worker then races to the next
checkpoint in ``run_conversion`` and bails out via ``ConversionCancelledError``
instead of running to completion.

This is cooperative, not pre-emptive: a long CPU-bound row loop inside a
converter will still finish before cancellation takes effect, because the
synchronous converter code has no yield points. The checkpoints in
``run_conversion`` bound the wait time to the duration of a single phase
(cleaning diff, convert, XSD validation). For typical SBA uploads that is
well under a minute.

The registry is thread-safe so it can be polled from the thread that
``asyncio.to_thread`` schedules the conversion on while the FastAPI event
loop writes to it.
"""

from __future__ import annotations

import threading


class ConversionCancelledError(Exception):
    """Raised by ``run_conversion`` when the job has been cancelled."""


class CancellationRegistry:
    """Thread-safe set of job IDs that should be cancelled on next check."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled: set[str] = set()

    def cancel(self, job_id: str) -> None:
        with self._lock:
            self._cancelled.add(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def clear(self, job_id: str) -> None:
        with self._lock:
            self._cancelled.discard(job_id)


# Module-level singleton. The FastAPI app is a single process, so sharing
# state in-process is fine. A multi-worker deployment would need Redis here.
registry = CancellationRegistry()
