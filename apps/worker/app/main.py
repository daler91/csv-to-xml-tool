import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routes import health, preview, convert, validate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="CSV-to-XML Worker", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(preview.router)
app.include_router(convert.router)
app.include_router(validate.router)

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
    logger.error("CATCH-ALL: %s /%s (no route matched)", request.method, path)
    return JSONResponse(
        status_code=404,
        content={
            "detail": f"No route matched: {request.method} /{path}",
            "registered_routes": _registered,
        },
    )
