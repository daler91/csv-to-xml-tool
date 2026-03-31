import logging
import os
import tempfile

import aiofiles
from fastapi import APIRouter, HTTPException

from ..models.schemas import PreviewRequest, PreviewResponse
from ..services.preview_service import read_csv_preview

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/preview",
    response_model=PreviewResponse,
    responses={
        400: {"description": "Invalid request parameters"},
        500: {"description": "Internal preview error"},
    },
)
async def preview(req: PreviewRequest):
    tmp_path = None
    try:
        # Write streamed CSV content to a temp file
        fd, tmp_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        async with aiofiles.open(tmp_path, mode="w", encoding="utf-8") as f:
            await f.write(req.file_content)

        result = read_csv_preview(tmp_path, req.converter_type)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Preview failed")
        raise HTTPException(status_code=500, detail="Internal preview error")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
