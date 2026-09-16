import asyncio
import logging

from fastapi import APIRouter, HTTPException

from ..logging_context import set_job_id
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
    # Bind the job id so preview logs correlate with the job like every other
    # route's do (QUAL-5); this was the one handler that left it as "-".
    set_job_id(req.job_id)
    try:
        # The web sends the uploaded CSV's content in the request body; the
        # worker no longer reads a shared volume (web and worker are separate
        # Railway services that cannot share one). job_id is for log correlation.
        result = await asyncio.to_thread(
            read_csv_preview, req.csv_content, req.converter_type
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Preview failed")
        raise HTTPException(status_code=500, detail="Internal preview error") from e
