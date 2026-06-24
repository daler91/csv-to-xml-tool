"""Path construction and validation for the worker service."""

import os
import re

DATA_DIR = os.path.realpath(os.environ.get("DATA_DIR", "/data"))


def sanitize_id(value: str) -> str:
    """Sanitize an identifier to only allow safe characters."""
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", value)
    if not sanitized:
        raise ValueError("Invalid identifier")
    return sanitized


def sanitize_filename(value: str) -> str:
    """Sanitize a filename to prevent path traversal."""
    basename = os.path.basename(value)
    sanitized = re.sub(r"[^a-zA-Z0-9_.\\-]", "_", basename)
    if not sanitized or sanitized.startswith("."):
        raise ValueError("Invalid filename")
    return sanitized


def resolve_input_csv(job_id: str, file_name: str) -> str:
    """Resolve a job's uploaded CSV path on the shared volume (ARCH-4).

    The web writes the input to ``{DATA_DIR}/uploads/{job_id}/{file_name}`` and
    now passes the job id + file name instead of the file body. We rebuild the
    path from those and prove it safe by confining it to DATA_DIR and requiring
    the file to exist — deliberately NOT re-running ``sanitize_filename`` on the
    leaf, whose rules diverge from the web's upload-time sanitizer and could
    point at a path the web never wrote. ``basename`` strips any directory
    component, and the realpath prefix + ``isfile`` checks reject traversal
    (``..``) and non-file targets.
    """
    safe_id = sanitize_id(job_id)
    leaf = os.path.basename(file_name)
    if not leaf:
        raise ValueError("Invalid filename")
    path = os.path.realpath(os.path.join(DATA_DIR, "uploads", safe_id, leaf))
    if not path.startswith(DATA_DIR + os.sep):
        raise ValueError("Invalid path")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    return path


def resolve_output_xml(job_id: str) -> str:
    """Resolve a job's deterministic output XML path on the shared volume (ARCH-4).

    Keyed only on the sanitized job id — matching where the web serves downloads
    and ``validate.py`` expects the file: ``{DATA_DIR}/output/{job_id}/{job_id}.xml``.
    The caller is responsible for creating the parent directory before writing.
    """
    safe_id = sanitize_id(job_id)
    path = os.path.realpath(
        os.path.join(DATA_DIR, "output", safe_id, f"{safe_id}.xml")
    )
    if not path.startswith(DATA_DIR + os.sep):
        raise ValueError("Invalid path")
    return path
