import logging
import os

from fastapi import APIRouter, HTTPException

from ..core.security import DATA_DIR, sanitize_id, sanitize_filename
from ..models.schemas import PreviewRequest, PreviewResponse
from ..services.preview_service import read_csv_preview

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/preview", response_model=PreviewResponse)
async def preview(req: PreviewRequest):
    try:
        safe_id = sanitize_id(req.job_id)
        safe_name = sanitize_filename(req.file_name)

        # Construct and validate path inline (CodeQL-recognized sanitizer pattern)
        csv_path = os.path.realpath(os.path.join(DATA_DIR, "uploads", safe_id, safe_name))
        if not csv_path.startswith(DATA_DIR + os.sep):
            raise HTTPException(status_code=400, detail="Invalid path")

        result = read_csv_preview(csv_path, req.converter_type)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="CSV file not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Preview failed")
        raise HTTPException(status_code=500, detail="Internal preview error")
