"""Job-scoped logging context (QUAL-5).

Threads the active job's id into every worker log record so all logs emitted
while a job is handled — including exception tracebacks that previously lost
context — are tagged ``[<job_id>]`` and correlatable across the web↔worker
boundary.

We install a ``LogRecord`` factory (rather than a per-handler ``Filter``) so the
``job_id`` attribute is present on *every* record. That keeps a ``%(job_id)s``
formatter from ever raising ``KeyError`` if a record reaches it without passing
through a particular handler's filters.

``asyncio.to_thread`` copies the current context into the worker thread, so a
``job_id_var.set(...)`` in the request handler is also visible to the
synchronous conversion pipeline's logs.
"""

import logging
import re
from contextvars import ContextVar

# "-" for records emitted outside any job (startup, healthcheck) so the format
# stays clean.
job_id_var: ContextVar[str] = ContextVar("job_id", default="-")

LOG_FORMAT = "%(asctime)s [%(job_id)s] %(name)s %(levelname)s: %(message)s"

_UNSAFE_JOB_ID = re.compile(r"[^a-zA-Z0-9_-]")
_MAX_JOB_ID_LEN = 64


def set_job_id(value: str | None) -> str:
    """Sanitize an incoming job id, bind it to the log context, and return it.

    The id arrives in the request body and lands in two places that must not
    accept arbitrary text: the ``[%(job_id)s]`` log prefix, where an embedded
    newline lets a caller forge whole log records (CWE-117), and the Redis key
    suffixes for progress/cancellation, where it can pollute the namespace.
    Anything outside ``[A-Za-z0-9_-]`` is dropped and the result is truncated.

    Returns "-" for an empty/None id so the log format stays aligned; callers
    use the returned value rather than the raw one.
    """
    cleaned = _UNSAFE_JOB_ID.sub("", str(value or ""))[:_MAX_JOB_ID_LEN] or "-"
    job_id_var.set(cleaned)
    return cleaned


def install_job_id_log_factory() -> None:
    """Wrap the LogRecord factory so every record carries the active job id."""
    old_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.job_id = job_id_var.get()
        return record

    logging.setLogRecordFactory(factory)
