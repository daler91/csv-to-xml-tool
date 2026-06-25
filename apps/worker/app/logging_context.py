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
from contextvars import ContextVar

# "-" for records emitted outside any job (startup, healthcheck) so the format
# stays clean.
job_id_var: ContextVar[str] = ContextVar("job_id", default="-")

LOG_FORMAT = "%(asctime)s [%(job_id)s] %(name)s %(levelname)s: %(message)s"


def install_job_id_log_factory() -> None:
    """Wrap the LogRecord factory so every record carries the active job id."""
    old_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.job_id = job_id_var.get()
        return record

    logging.setLogRecordFactory(factory)
