import asyncio
import logging
import os
import shutil
import tempfile

from fastapi import APIRouter, HTTPException

from ..logging_context import job_id_var
from ..models.schemas import ConvertRequest, ConvertResponse
from ..services.cancellation import ConversionCancelledError
from ..services.cancellation import registry as cancel_registry
from ..services.conversion_service import run_conversion, EmptyCSVError
from ..services.column_requirements import RequiredColumnsMissingError
from ..services.progress import registry as progress_registry

logger = logging.getLogger(__name__)

router = APIRouter()


def _write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@router.post(
    "/convert",
    response_model=ConvertResponse,
    responses={
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
    tmp_dir = None
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

        # The web sends the CSV content in the request body and persists the XML
        # we return — web and worker are separate Railway services and cannot
        # share a volume. Stage the input and output in a worker-local temp dir;
        # nothing is read from or written to a shared disk.
        tmp_dir = await asyncio.to_thread(tempfile.mkdtemp, prefix="convert_")
        csv_path = os.path.join(tmp_dir, "input.csv")
        xml_path = os.path.join(tmp_dir, "output.xml")
        await asyncio.to_thread(_write_text, csv_path, req.csv_content)

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

        # Return the converted XML text for the web to persist on its own disk;
        # the on-disk path is worker-local and meaningless to the web.
        xml_content = await asyncio.to_thread(_read_text, xml_path)
        result.pop("xml_path", None)
        result["xml_content"] = xml_content
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
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request parameters")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Conversion failed")
        raise HTTPException(status_code=500, detail="Internal conversion error")
    finally:
        # Drop the cancellation flag and progress snapshot so the same job_id
        # can be reused after a re-upload, and remove the worker-local temp dir.
        # Offloaded to a thread so the Redis round-trips don't block the loop.
        await asyncio.to_thread(cancel_registry.clear, req.job_id)
        await asyncio.to_thread(progress_registry.clear, req.job_id)
        if tmp_dir:
            await asyncio.to_thread(shutil.rmtree, tmp_dir, ignore_errors=True)


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
