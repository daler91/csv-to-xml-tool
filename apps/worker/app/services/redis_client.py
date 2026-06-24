"""Shared Redis client for the worker's cross-process coordination state.

The worker's progress and cancellation registries (``progress.py`` /
``cancellation.py``) used to be in-process ``dict``/``set`` singletons, which
silently break the moment the worker runs more than one uvicorn process or
replica: a progress poll or a cancel can land on a process that isn't the one
running the conversion. Both now live in the Redis that is already part of the
stack (ARCH-2/ARCH-3), keyed by ``job_id`` so any process sees the same state.

This module owns the single Redis connection both registries share.

Design choices (mirroring ``apps/web/src/lib/redis.ts``):

* **Synchronous** client. The conversion runs in ``asyncio.to_thread`` and its
  progress / cancellation callbacks are plain sync functions that cannot
  ``await``; a sync client is called directly from that thread. redis-py's
  connection pool is thread-safe, so the same client also serves the FastAPI
  event loop (the route handlers offload their calls via ``asyncio.to_thread``).
* **Lazy, first-use** construction. Importing this module (transitively, any
  worker route or a test) must not open a socket — only the first real command
  does. This keeps build/import/test tooling from spawning a live connection.
* **Short socket timeouts** so a stalled Redis fails fast instead of hanging the
  conversion thread (the progress callback fires roughly every 25 rows).

Callers treat Redis as best-effort: every registry operation is wrapped so a
Redis outage degrades the progress bar / cancellation signal rather than failing
a valid federal conversion. See the registries for the fail-soft semantics.
"""

from __future__ import annotations

import os

import redis

# Single namespace shared with the web's durable queue (``csvxml:jobs:*`` in
# apps/web/src/lib/job-queue.ts). Keep new keys under the same prefix.
PREFIX = "csvxml:"
PROGRESS_PREFIX = f"{PREFIX}progress:"
CANCEL_PREFIX = f"{PREFIX}cancel:"

# Orphan-cleanup backstop: a key whose owning job died without clearing it
# expires on its own. Comfortably above the 60-min reaper deadline
# (REAP_DEADLINE_MS) so it never expires a key out from under a live job.
TTL_SECONDS = 2 * 60 * 60  # 2 hours

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    """Return the shared Redis client, creating it on first use.

    Thread-safe to call from both the conversion worker thread and the event
    loop: redis-py hands out a pooled connection per command.
    """
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379"),
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
        )
    return _client


def set_client(client: redis.Redis | None) -> None:
    """Inject a client (e.g. a fakeredis instance) for tests, or reset to None.

    Passing ``None`` forces the next ``get_client()`` to rebuild the real
    client, so tests can restore the default in teardown.
    """
    global _client
    _client = client


def progress_key(job_id: str) -> str:
    return f"{PROGRESS_PREFIX}{job_id}"


def cancel_key(job_id: str) -> str:
    return f"{CANCEL_PREFIX}{job_id}"
