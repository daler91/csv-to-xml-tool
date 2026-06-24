"""Redis-backed progress registry for in-flight conversions.

Partners watching the progress page need row-level feedback, but the
worker synchronously runs `run_conversion` inside `asyncio.to_thread`
and returns once the whole job is done — the web layer can't see what
the converter is doing mid-run.

The converter populates a per-job snapshot via the BaseConverter
progress callback, and a dedicated route exposes it so the web layer
can merge it into its existing /api/jobs/[id] polling response. See
UX_REVIEW.md §3.6.

State lives in Redis (ARCH-2/ARCH-3) under ``csvxml:progress:{job_id}``
so it survives across worker processes/replicas — the converter thread
on one process writes it while a progress poll served by any process
reads it. The public API (``registry.update/get/clear``) is unchanged
from the previous in-memory implementation, so callers don't change.

Redis is best-effort here: progress is a UX nicety, so every operation
fails soft (a Redis blip drops a snapshot rather than failing the
conversion). See ``redis_client.py`` for the shared connection.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict

from .redis_client import TTL_SECONDS, get_client, progress_key

logger = logging.getLogger(__name__)


@dataclass
class ProgressSnapshot:
    processed: int
    total: int
    # Unix epoch seconds when this snapshot was last updated, so the
    # web layer can compute rate-based ETAs without trusting client
    # clocks.
    updated_at: float


class ProgressRegistry:
    """Redis-backed map of job_id -> ProgressSnapshot (as a hash)."""

    def update(self, job_id: str, processed: int, total: int) -> None:
        key = progress_key(job_id)
        try:
            # Refresh the TTL on every update so a long-running job never
            # expires its own progress mid-run; the TTL only reaps snapshots
            # whose job died without clearing them.
            pipe = get_client().pipeline()
            pipe.hset(
                key,
                mapping={
                    "processed": processed,
                    "total": total,
                    "updated_at": time.time(),
                },
            )
            pipe.expire(key, TTL_SECONDS)
            pipe.execute()
        except Exception:
            logger.warning("progress.update failed for job %s", job_id, exc_info=True)

    def get(self, job_id: str) -> dict | None:
        try:
            raw = get_client().hgetall(progress_key(job_id))
        except Exception:
            logger.warning("progress.get failed for job %s", job_id, exc_info=True)
            return None
        if not raw:
            return None
        try:
            snap = ProgressSnapshot(
                processed=int(raw["processed"]),
                total=int(raw["total"]),
                updated_at=float(raw["updated_at"]),
            )
        except (KeyError, ValueError):
            # A partially-written or malformed hash — treat as "no progress".
            logger.warning("progress.get got malformed snapshot for job %s", job_id)
            return None
        return asdict(snap)

    def clear(self, job_id: str) -> None:
        try:
            get_client().delete(progress_key(job_id))
        except Exception:
            logger.warning("progress.clear failed for job %s", job_id, exc_info=True)


# Module-level singleton. State is in Redis, so this is just a stateless
# façade — every process shares the same underlying snapshots.
registry = ProgressRegistry()
