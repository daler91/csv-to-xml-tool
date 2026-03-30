"""Path construction and validation for the worker service.

All file paths are constructed server-side from trusted DATA_DIR + sanitized
identifiers. No user-provided file paths are accepted by any endpoint.
"""

import os
import re

DATA_DIR = os.path.realpath(os.environ.get("DATA_DIR", "/data"))


def _sanitize_id(value: str) -> str:
    """Sanitize an identifier to only allow safe characters."""
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", value)
    if not sanitized:
        raise ValueError("Invalid identifier")
    return sanitized


def _sanitize_filename(value: str) -> str:
    """Sanitize a filename to prevent path traversal."""
    # Strip any directory components
    basename = os.path.basename(value)
    # Remove anything that isn't alphanumeric, dash, underscore, dot
    sanitized = re.sub(r"[^a-zA-Z0-9_.\-]", "_", basename)
    if not sanitized or sanitized.startswith("."):
        raise ValueError("Invalid filename")
    return sanitized


def get_upload_path(job_id: str, file_name: str) -> str:
    """Construct the path where an uploaded CSV is stored."""
    safe_id = _sanitize_id(job_id)
    safe_name = _sanitize_filename(file_name)
    return os.path.join(DATA_DIR, "uploads", safe_id, safe_name)


def get_output_path(job_id: str) -> str:
    """Construct the output XML path for a job."""
    safe_id = _sanitize_id(job_id)
    output_dir = os.path.join(DATA_DIR, "output", safe_id)
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, f"{safe_id}.xml")
