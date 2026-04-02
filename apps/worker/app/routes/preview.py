import asyncio
import logging
import os
import tempfile

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
    tmp = None
    try:
        # Write streamed CSV content to a temp file
        tmp = await asyncio.to_thread(
            tempfile.NamedTemporaryFile,
            suffix=".csv", delete=False, mode="w", encoding="utf-8",
        )
        await asyncio.to_thread(tmp.write, req.file_content)
        await asyncio.to_thread(tmp.close)

        result = await asyncio.to_thread(read_csv_preview, tmp.name, req.converter_type)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Preview failed")
        raise HTTPException(status_code=500, detail="Internal preview error")
    finally:
        if tmp and os.path.exists(tmp.name):
            os.unlink(tmp.name)
