import asyncio
import logging
import os

from fastapi import APIRouter, HTTPException

from ..core.security import resolve_input_csv, resolve_output_xml
from ..logging_context import job_id_var
from ..models.schemas import ConvertRequest, ConvertResponse
from ..services.cancellation import ConversionCancelledError
from ..services.cancellation import registry as cancel_registry
from ..services.conversion_service import run_conversion, EmptyCSVError
from ..services.column_requirements import RequiredColumnsMissingError
from ..services.progress import registry as progress_registry

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/convert",
    response_model=ConvertResponse,
    responses={
        404: {"description": "CSV file not found"},
        400: {"description": "Invalid request parameters"},
        409: {"description": "Conversion cancelled by user"},
        422: {
            "description": "Unprocessable CSV: required columns missing or the file is empty"
        },
        500: {"description": "Internal conversion error"},
    },
)
async def convert(req: ConvertRequest):
    # Bind the job id for the rest of this request's logs (incl. the conversion
    # thread, since asyncio.to_thread copies the context) — QUAL-5 correlation.
    job_id_var.set(req.job_id)
    try:
        # Clear any stale progress snapshot left by a previous attempt at this
        # job_id. ARCH-1 can re-queue the same job_id on a transient failure
        # (attempts run sequentially), so resetting on entry stops a poll from
        # reading the dead attempt's snapshot — the new attempt then writes
        # fresh progress. We deliberately do NOT clear the cancel flag here: it
        # is only ever set after the web has authoritatively marked the job
        # cancelled, so it never applies to a fresh legitimate run, and clearing
        # it could wipe a cancel that landed in the gap before the worker started.
        await asyncio.to_thread(progress_registry.clear, req.job_id)

        # ARCH-4: read the input straight off the shared volume and write the
        # output back to it, instead of streaming the file in/out as JSON. Both
        # paths are derived from the job id (+ file name) and confined to
        # DATA_DIR; an invalid path raises ValueError -> 400, a missing input
        # FileNotFoundError -> 404 via the handlers below.
        csv_path = await asyncio.to_thread(
            resolve_input_csv, req.job_id, req.file_name
        )
        xml_path = await asyncio.to_thread(resolve_output_xml, req.job_id)
        await asyncio.to_thread(
            os.makedirs, os.path.dirname(xml_path), exist_ok=True
        )

        # Capture job_id for the cancellation callback; run_conversion will
        # poll cancel_registry.is_cancelled between phases and raise if
        # the user clicked Cancel. The progress callback writes into
        # the progress registry, which a separate route exposes so the
        # web layer can draw the progress bar.
        job_id = req.job_id

        def _on_progress(processed: int, total: int) -> None:
            progress_registry.update(job_id, processed, total)

        result = await asyncio.to_thread(
            run_conversion,
            csv_path=csv_path,
            xml_path=xml_path,
            converter_type=req.converter_type,
            column_mapping=req.column_mapping,
            is_cancelled=lambda: cancel_registry.is_cancelled(job_id),
            on_progress=_on_progress,
        )

        # run_conversion already set result["xml_path"] = xml_path; the XML now
        # lives on the shared volume for the web to serve. No content over HTTP.
        return result
    except ConversionCancelledError:
        logger.info("Conversion cancelled for job %s", req.job_id)
        raise HTTPException(status_code=409, detail="Conversion cancelled")
    except RequiredColumnsMissingError as e:
        # CONV-1: surface exactly which required columns are missing instead of a
        # generic 400, so the web layer can record/show what the user must fix.
        raise HTTPException(status_code=422, detail=str(e))
    except EmptyCSVError as e:
        # CONV-6: headers-only / empty CSV is unprocessable; map to 422 (before the
        # generic ValueError handler, since EmptyCSVError subclasses ValueError).
        raise HTTPException(status_code=422, detail=str(e))
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
        # Drop the cancellation flag and progress snapshot so the same job_id
        # can be reused after a re-upload. Offloaded to a thread so the Redis
        # round-trips don't block the event loop. (No scratch files to clean up
        # anymore — ARCH-4 reads/writes the shared volume directly.)
        await asyncio.to_thread(cancel_registry.clear, req.job_id)
        await asyncio.to_thread(progress_registry.clear, req.job_id)


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
    job_id_var.set(job_id)
    await asyncio.to_thread(cancel_registry.cancel, job_id)
    return {"job_id": job_id, "cancelled": True}


@router.get(
    "/convert/{job_id}/progress",
    responses={
        200: {"description": "Current progress snapshot"},
        404: {"description": "No progress recorded for this job"},
    },
)
async def get_convert_progress(job_id: str):
    """Return the in-memory progress snapshot for a running job.

    The web layer polls this alongside its DB read in
    `/api/jobs/[id]` and merges the ``processed`` / ``total`` /
    ``updated_at`` fields into the response the progress page
    consumes. Returns 404 if no snapshot is recorded — typically
    because the job already finished (the registry is cleared in
    the /convert route's finally block) or because the worker
    hasn't started yet.
    """
    job_id_var.set(job_id)
    snap = await asyncio.to_thread(progress_registry.get, job_id)
    if snap is None:
        raise HTTPException(
            status_code=404, detail="No progress recorded for this job"
        )
    return snap
