import os

from fastapi import APIRouter

from ..core.paths import REQUIRED_SCHEMA_FILES

router = APIRouter()

DATA_DIR = os.environ.get("DATA_DIR", "/data")


@router.get("/health")
async def health():
    checks = {"api": "ok"}

    # The schemas are what the worker actually needs to do its job: without
    # them every document comes back "invalid" with no reasons. Startup already
    # refuses to come up without them (see main.lifespan); this reports the same
    # condition for anything probing a running container.
    from .validate import SCHEMAS_DIR  # late import so tests can patch it
    checks["schemas"] = "ok" if all(
        os.path.exists(os.path.join(SCHEMAS_DIR, name)) for name in REQUIRED_SCHEMA_FILES
    ) else "error"

    # Informational only, and deliberately excluded from `status` below.
    # Conversion payloads travel over HTTP rather than a shared volume, so the
    # worker no longer reads or writes DATA_DIR -- on a platform that mounts no
    # volume this is expected to be absent, and letting it degrade the overall
    # status would fail the healthcheck of a perfectly functional worker.
    try:
        os.listdir(DATA_DIR)
        checks["data_dir"] = "ok"
    except OSError:
        checks["data_dir"] = "unavailable"

    required = {k: v for k, v in checks.items() if k != "data_dir"}
    status = "ok" if all(v == "ok" for v in required.values()) else "degraded"
    return {"status": status, "checks": checks}
