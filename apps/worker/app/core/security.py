"""Path validation to prevent path traversal attacks."""

import os
import re

DATA_DIR = os.environ.get("DATA_DIR", "/data")


def validate_path(path: str) -> str:
    """
    Validate that a file path resolves within the allowed DATA_DIR.
    Returns the resolved absolute path, or raises ValueError.
    """
    resolved = os.path.realpath(path)
    allowed = os.path.realpath(DATA_DIR)

    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        raise ValueError("Path is outside the allowed data directory")

    return resolved


def safe_output_path(job_id: str) -> str:
    """
    Construct a safe output XML path for a given job ID.
    The job_id is sanitized to prevent path traversal.
    """
    # Only allow alphanumeric, hyphens, and underscores in job_id
    sanitized_id = re.sub(r"[^a-zA-Z0-9_-]", "", job_id)
    if not sanitized_id:
        raise ValueError("Invalid job ID")

    output_dir = os.path.join(os.path.realpath(DATA_DIR), "output", sanitized_id)
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, f"{sanitized_id}.xml")
