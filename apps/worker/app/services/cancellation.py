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

The cancellation flag lives in Redis (ARCH-2/ARCH-3) under
``csvxml:cancel:{job_id}`` so the cancel signal reaches the conversion no
matter which worker process received the cancel request. The public API
(``registry.cancel/is_cancelled/clear``) is unchanged from the previous
in-memory implementation.

Fail-soft semantics: if Redis is unavailable, ``is_cancelled`` returns
**False** so a transient Redis blip can never abort a legitimate in-flight
conversion. That is safe because the web database — not this signal — is
authoritative: the job is already marked ``cancelled`` there, and the queue
consumer discards any result the worker produces for a cancelled job. A
missed signal only costs wasted CPU until the cooperative checkpoints finish.
"""

from __future__ import annotations

import logging

from .redis_client import TTL_SECONDS, cancel_key, get_client

logger = logging.getLogger(__name__)


class ConversionCancelledError(Exception):
    """Raised by ``run_conversion`` when the job has been cancelled."""


class CancellationRegistry:
    """Redis-backed set of job IDs that should be cancelled on next check."""

    def cancel(self, job_id: str) -> None:
        try:
            get_client().set(cancel_key(job_id), "1", ex=TTL_SECONDS)
        except Exception:
            # Best-effort: the DB already holds the authoritative cancelled
            # state, so a lost signal only means the worker keeps crunching
            # until it finishes. Surface it so the degradation is observable.
            logger.warning("cancellation.cancel failed for job %s", job_id, exc_info=True)

    def is_cancelled(self, job_id: str) -> bool:
        try:
            return bool(get_client().exists(cancel_key(job_id)))
        except Exception:
            # Fail-soft: never cancel a valid conversion because Redis hiccuped.
            logger.warning(
                "cancellation.is_cancelled failed for job %s; treating as not cancelled",
                job_id,
                exc_info=True,
            )
            return False

    def clear(self, job_id: str) -> None:
        try:
            get_client().delete(cancel_key(job_id))
        except Exception:
            logger.warning("cancellation.clear failed for job %s", job_id, exc_info=True)


# Module-level singleton. State is in Redis, so this is just a stateless
# façade shared by every worker process.
registry = CancellationRegistry()
