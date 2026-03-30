import logging

from fastapi import APIRouter, HTTPException

from ..core.security import get_upload_path
from ..models.schemas import PreviewRequest, PreviewResponse
from ..services.preview_service import read_csv_preview

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/preview", response_model=PreviewResponse)
async def preview(req: PreviewRequest):
    try:
        csv_path = get_upload_path(req.job_id, req.file_name)
        result = read_csv_preview(csv_path, req.converter_type)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="CSV file not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Preview failed")
        raise HTTPException(status_code=500, detail="Internal preview error")
