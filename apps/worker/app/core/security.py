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
