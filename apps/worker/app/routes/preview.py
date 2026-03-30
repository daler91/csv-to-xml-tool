import logging

from fastapi import APIRouter, HTTPException

from ..models.schemas import PreviewRequest, PreviewResponse
from ..services.preview_service import read_csv_preview

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/preview", response_model=PreviewResponse)
async def preview(req: PreviewRequest):
    try:
        result = read_csv_preview(req.csv_path, req.converter_type)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="CSV file not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Preview failed")
        raise HTTPException(status_code=500, detail="Internal preview error")
