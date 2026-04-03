import os

from fastapi import APIRouter

router = APIRouter()

DATA_DIR = os.environ.get("DATA_DIR", "/data")


@router.get("/health")
async def health():
    checks = {"api": "ok"}

    # Verify data directory is accessible
    try:
        os.listdir(DATA_DIR)
        checks["data_dir"] = "ok"
    except OSError:
        checks["data_dir"] = "error"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
