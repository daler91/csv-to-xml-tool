import logging
import os

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .core.auth import require_worker_token
from .routes import health, preview, convert, validate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="CSV-to-XML Worker", version="1.2.0")

_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

# Defense-in-depth DoS guard: reject oversized request bodies before they are
# parsed into memory. The web layer enforces a 50MB *file* cap; this is a
# generous backstop on the JSON envelope (CSV content is sent as a string field).
MAX_REQUEST_BYTES = int(os.environ.get("MAX_REQUEST_BYTES", str(100 * 1024 * 1024)))

# The worker is called server-to-server by the web backend, never from a
# browser, so CORS can be tight: only the methods/headers we actually use.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def limit_request_body_size(request: Request, call_next):
    """Reject requests whose declared body exceeds MAX_REQUEST_BYTES."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            return JSONResponse(
                status_code=400, content={"detail": "Invalid Content-Length"}
            )
        if declared > MAX_REQUEST_BYTES:
            return JSONResponse(
                status_code=413, content={"detail": "Request body too large"}
            )
    return await call_next(request)


# /health stays unauthenticated so container/platform healthchecks keep working.
# Every functional endpoint requires the shared worker token (SEC-1).
app.include_router(health.router)
app.include_router(preview.router, dependencies=[Depends(require_worker_token)])
app.include_router(convert.router, dependencies=[Depends(require_worker_token)])
app.include_router(validate.router, dependencies=[Depends(require_worker_token)])

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
    return JSONResponse(
        status_code=404,
        content={
            "detail": "No route matched",
            "registered_routes": _registered,
        },
    )
