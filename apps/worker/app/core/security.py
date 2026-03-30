"""Path validation to prevent path traversal attacks."""

import os

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
