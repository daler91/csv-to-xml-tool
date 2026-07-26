import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .core.auth import require_worker_token
from .core.paths import verify_schemas_dir
from .logging_context import LOG_FORMAT, install_job_id_log_factory
from .routes import health, preview, convert, validate, fix

# Tag every log record with the active job id (default "-") so logs are
# correlatable across the web↔worker boundary (QUAL-5).
install_job_id_log_factory()
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Refuse to start when the XSD schemas can't be found.

    Without them the worker still answers every request, but reports every
    document as invalid with no reasons attached -- a silent failure in a
    federal-reporting tool. Better to not come up at all. Checked here rather
    than at import time so importing the app (as the tests do) stays side-effect
    free. Imported lazily to pick up any monkeypatched SCHEMAS_DIR.
    """
    from .routes.validate import SCHEMAS_DIR
    verify_schemas_dir(SCHEMAS_DIR)
    logger.info("XSD schemas found at %s", os.path.realpath(SCHEMAS_DIR))
    yield


# The interactive docs and the OpenAPI schema were served unauthenticated,
# handing anyone the worker's full request/response contract. They're useful in
# development, so they're kept there and disabled everywhere else.
_DOCS_ENABLED = os.environ.get("ENVIRONMENT", "development").lower() not in {
    "production",
    "prod",
}

app = FastAPI(
    title="CSV-to-XML Worker",
    version="1.2.0",
    lifespan=lifespan,
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)

_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

# Defense-in-depth DoS guard: reject oversized request bodies before they are
# parsed into memory. The web layer enforces a 50MB *file* cap; this is a
# generous backstop on the JSON envelope (CSV content is sent as a string field).
MAX_REQUEST_BYTES = int(os.environ.get("MAX_REQUEST_BYTES", str(100 * 1024 * 1024)))


class _RequestTooLarge(Exception):
    """Raised from the receive wrapper when a streamed body exceeds the cap."""


async def _send_json(send, status_code: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    """Reject request bodies exceeding MAX_REQUEST_BYTES.

    Checks the declared Content-Length first (rejects before anything is read),
    then counts bytes as the body streams. The streaming half is the point: the
    previous version trusted Content-Length alone, so a request sent with
    ``Transfer-Encoding: chunked`` and no Content-Length skipped the guard
    entirely and Starlette buffered the whole body -- the cap was bypassable by
    omitting one header.

    Written as raw ASGI rather than ``@app.middleware("http")`` deliberately:
    Starlette's BaseHTTPMiddleware hands the *original* receive channel to
    ``call_next``, so replacing ``request._receive`` there has no effect on what
    the endpoint actually reads.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Read the module global at call time so tests (and env reloads) can
        # override it without rebuilding the middleware stack.
        max_bytes = MAX_REQUEST_BYTES

        declared_raw = dict(scope.get("headers") or {}).get(b"content-length")
        if declared_raw is not None:
            try:
                declared = int(declared_raw)
            except ValueError:
                return await _send_json(send, 400, {"detail": "Invalid Content-Length"})
            if declared < 0:
                return await _send_json(send, 400, {"detail": "Invalid Content-Length"})
            if declared > max_bytes:
                return await _send_json(send, 413, {"detail": "Request body too large"})

        received = 0
        too_large = False
        responded = False

        async def limited_receive():
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    # Truncate rather than raise: an exception here is caught by
                    # FastAPI's body parsing and reported as "error parsing the
                    # body" (400), which hides the real reason. Ending the body
                    # early lets the request finish, and guarded_send below
                    # replaces whatever the endpoint produced with a 413.
                    too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def guarded_send(message):
            nonlocal responded
            if too_large:
                if not responded:
                    responded = True
                    await _send_json(
                        send, 413, {"detail": "Request body too large"}
                    )
                return  # drop the endpoint's own response
            await send(message)

        await self.app(scope, limited_receive, guarded_send)
        if too_large and not responded:
            await _send_json(send, 413, {"detail": "Request body too large"})


# The worker is called server-to-server by the web backend, never from a
# browser, so CORS can be tight: only the methods/headers we actually use.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


app.add_middleware(BodySizeLimitMiddleware)


# /health stays unauthenticated so container/platform healthchecks keep working.
# Every functional endpoint requires the shared worker token (SEC-1).
app.include_router(health.router)
app.include_router(preview.router, dependencies=[Depends(require_worker_token)])
app.include_router(convert.router, dependencies=[Depends(require_worker_token)])
app.include_router(validate.router, dependencies=[Depends(require_worker_token)])
app.include_router(fix.router, dependencies=[Depends(require_worker_token)])

# Log all registered routes at startup
_registered = []
for route in app.routes:
    if hasattr(route, "methods"):
        _registered.append(f"{route.methods} {route.path}")
logger.info("=== Registered Routes ===")
for r in _registered:
    logger.info(f"  {r}")
logger.info("=========================")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(path: str, request: Request):
    sanitized_path = path.replace("\n", "").replace("\r", "")[:200]
    logger.error("CATCH-ALL: %s /%s (no route matched)", request.method, sanitized_path)
    # The route table goes to the log, not the response. Returning it here
    # handed the worker's entire API surface to any anonymous caller who
    # guessed a wrong path; the same information is already logged at startup
    # for whoever is actually debugging.
    body = {"detail": "No route matched"}
    if _DOCS_ENABLED:
        body["registered_routes"] = _registered
    return JSONResponse(status_code=404, content=body)
