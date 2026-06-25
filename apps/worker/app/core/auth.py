"""Service-to-service authentication for the worker API (SEC-1).

The worker is called only by the web backend, never directly by browsers, so
every functional endpoint requires a shared bearer token (``WORKER_AUTH_TOKEN``).
The token is read at import time, matching the existing env-var convention used
elsewhere in the worker (see ``core/security.py`` and ``main.py``).

Fail-closed: if no token is configured the worker refuses functional requests
rather than silently serving them unauthenticated.
"""

import os
import secrets

from fastapi import Header, HTTPException, status

WORKER_AUTH_TOKEN = os.environ.get("WORKER_AUTH_TOKEN", "")


def require_worker_token(authorization: str | None = Header(default=None)) -> None:
    """Enforce the shared bearer token on a request.

    Raises 503 when the token isn't configured (server misconfiguration) and
    401 when the ``Authorization`` header is missing or doesn't match. The
    comparison is constant-time to avoid leaking the token via timing.
    """
    if not WORKER_AUTH_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker authentication is not configured",
        )

    expected = f"Bearer {WORKER_AUTH_TOKEN}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing worker credentials",
        )
