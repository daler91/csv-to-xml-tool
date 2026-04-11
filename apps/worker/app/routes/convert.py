import asyncio
import logging
import os
import tempfile

from fastapi import APIRouter, HTTPException

from ..models.schemas import ConvertRequest, ConvertResponse
from ..services.cancellation import ConversionCancelledError, registry
from ..services.conversion_service import run_conversion

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/convert",
    response_model=ConvertResponse,
    responses={
        404: {"description": "CSV file not found"},
        400: {"description": "Invalid request parameters"},
        409: {"description": "Conversion cancelled by user"},
        500: {"description": "Internal conversion error"},
    },
)
async def convert(req: ConvertRequest):
    tmp_csv = None
    tmp_xml = None
    try:
        # Write streamed CSV content to a temp file
        tmp_csv = await asyncio.to_thread(
            tempfile.NamedTemporaryFile,
            suffix=".csv", delete=False, mode="w", encoding="utf-8",
        )
        await asyncio.to_thread(tmp_csv.write, req.file_content)
        await asyncio.to_thread(tmp_csv.close)

        # Create a temp file for XML output
        tmp_xml = await asyncio.to_thread(
            tempfile.NamedTemporaryFile,
            suffix=".xml", delete=False,
        )
        await asyncio.to_thread(tmp_xml.close)

        # Capture job_id for the cancellation callback; run_conversion will
        # poll registry.is_cancelled between phases and raise if the user
        # clicked Cancel.
        job_id = req.job_id

        result = await asyncio.to_thread(
            run_conversion,
            csv_path=tmp_csv.name,
            xml_path=tmp_xml.name,
            converter_type=req.converter_type,
            column_mapping=req.column_mapping,
            is_cancelled=lambda: registry.is_cancelled(job_id),
        )

        # Read generated XML and include in response
        xml_content = None
        if await asyncio.to_thread(os.path.exists, tmp_xml.name):
            def _read_xml():
                with open(tmp_xml.name, "r", encoding="utf-8") as f:
                    return f.read()
            xml_content = await asyncio.to_thread(_read_xml)

        result["xml_content"] = xml_content
        return result
    except ConversionCancelledError:
        logger.info("Conversion cancelled for job %s", req.job_id)
        raise HTTPException(status_code=409, detail="Conversion cancelled")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="CSV file not found")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request parameters")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Conversion failed")
        raise HTTPException(status_code=500, detail="Internal conversion error")
    finally:
        # Drop the cancellation flag so the same job_id can be reused after
        # a re-upload, and clean up scratch files.
        registry.clear(req.job_id)
        if tmp_csv and os.path.exists(tmp_csv.name):
            os.unlink(tmp_csv.name)
        if tmp_xml and os.path.exists(tmp_xml.name):
            os.unlink(tmp_xml.name)


@router.post(
    "/convert/{job_id}/cancel",
    responses={
        200: {"description": "Cancellation requested"},
    },
)
async def cancel_convert(job_id: str):
    """Mark a job for cooperative cancellation.

    This is a best-effort signal to an in-flight conversion running in
    ``asyncio.to_thread``. The synchronous converter cannot be pre-empted,
    so cancellation takes effect at the next checkpoint inside
    ``run_conversion``. If the job has already finished, this is a no-op.

    The web layer's database state is authoritative; this endpoint exists
    so the worker can stop wasting CPU on a cancelled job as quickly as
    the cooperative checkpoints allow.
    """
    registry.cancel(job_id)
    return {"job_id": job_id, "cancelled": True}
