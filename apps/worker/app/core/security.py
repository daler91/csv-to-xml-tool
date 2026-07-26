"""Filesystem configuration for the worker service.

Previously also held ``sanitize_id``/``sanitize_filename``, written for the era
when the web passed file paths over a shared volume. Conversion payloads travel
over HTTP now and every path is server-chosen inside a ``mkdtemp``, so neither
had a caller. Job-id sanitization -- the one place that input still needed
cleaning -- lives in ``logging_context.set_job_id``, next to the log format and
the Redis key builders that consume it.
"""

import os

DATA_DIR = os.path.realpath(os.environ.get("DATA_DIR", "/data"))
