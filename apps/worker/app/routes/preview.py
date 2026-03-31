import logging
import os
import tempfile

from fastapi import APIRouter, HTTPException

from ..models.schemas import PreviewRequest, PreviewResponse
from ..services.preview_service import read_csv_preview

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/preview", response_model=PreviewResponse)
async def preview(req: PreviewRequest):
    tmp = None
    try:
        # Write streamed CSV content to a temp file
        tmp = tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8"
        )
        tmp.write(req.file_content)
        tmp.close()

        result = read_csv_preview(tmp.name, req.converter_type)
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
