import asyncio
import logging

from fastapi import APIRouter, HTTPException

from ..core.security import resolve_input_csv
from ..models.schemas import PreviewRequest, PreviewResponse
from ..services.preview_service import read_csv_preview

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/preview",
    response_model=PreviewResponse,
    responses={
        404: {"description": "CSV file not found"},
        400: {"description": "Invalid request parameters"},
        500: {"description": "Internal preview error"},
    },
)
async def preview(req: PreviewRequest):
    try:
        # ARCH-4: read the uploaded CSV straight off the shared volume by path
        # (derived from job_id + file_name, confined to DATA_DIR) instead of
        # receiving its content in the request body.
        csv_path = await asyncio.to_thread(
            resolve_input_csv, req.job_id, req.file_name
        )
        result = await asyncio.to_thread(
            read_csv_preview, csv_path, req.converter_type
        )
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
