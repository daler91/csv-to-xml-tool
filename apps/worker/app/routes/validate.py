import asyncio
import logging
import os
import shutil
import sys
import tempfile

from fastapi import APIRouter, HTTPException

# Ensure src is importable
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.xml_validator import validate_against_xsd
from src.xsd_error_mapping import build_error_details

from ..logging_context import job_id_var
from ..models.schemas import ValidateXsdRequest, ValidateXsdResponse

logger = logging.getLogger(__name__)

router = APIRouter()

SCHEMAS_DIR = os.environ.get("SCHEMAS_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "..", "schemas"))

# Which XSD each schema_type validates against. training-client output is
# Form 641 counseling-format XML, so it uses the counseling XSD (same map as
# conversion_service's inline post-convert validation).
XSD_MAP = {
    "counseling": "SBA_NEXUS_Counseling-2-14.xsd",
    "training": "SBA_NEXUS_Training-2-25-2025.xsd",
    "training-client": "SBA_NEXUS_Counseling-2-14.xsd",
}


def _write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


@router.post(
    "/validate-xsd",
    response_model=ValidateXsdResponse,
    responses={
        400: {"description": "Unknown schema type or empty XML content"},
        500: {"description": "Internal validation error"},
    },
)
async def validate_xsd(req: ValidateXsdRequest):
    """Validate XML content against its XSD schema.

    The web sends the XML text in the request body and gets the validation
    result back — web and worker are separate Railway services that cannot
    share a volume, so nothing is read from a shared disk. job_id is for log
    correlation only. Malformed/unparseable XML is a *result* (is_valid=false
    with the parse error in errors), not a 500.
    """
    job_id_var.set(req.job_id)

    if req.schema_type not in XSD_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown schema type: {req.schema_type}")
    if not req.xml_content.strip():
        raise HTTPException(status_code=400, detail="xml_content must not be empty")

    xsd_file = os.path.join(SCHEMAS_DIR, XSD_MAP[req.schema_type])

    tmp_dir = None
    try:
        # Stage the XML in a worker-local temp dir (same pattern as /convert)
        # and validate it the way conversion_service does post-convert.
        tmp_dir = await asyncio.to_thread(tempfile.mkdtemp, prefix="validate_")
        xml_path = os.path.join(tmp_dir, "input.xml")
        await asyncio.to_thread(_write_text, xml_path, req.xml_content)

        result = await asyncio.to_thread(validate_against_xsd, xml_path, xsd_file)
        errors = result.get("errors", [])
        is_valid = result.get("is_valid", False)
        error_details: list[dict] = []
        if not is_valid and errors:
            # Feature 2.4: map each raw error string back to the record (row)
            # and CSV column it came from. Degrades to null fields when the
            # XML is unparseable or an error can't be traced to a record.
            error_details = await asyncio.to_thread(
                build_error_details, xml_path, errors, req.schema_type
            )
        return {
            "is_valid": is_valid,
            "errors": errors,
            "error_count": len(errors),
            "error_details": error_details,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("XSD validation failed")
        raise HTTPException(status_code=500, detail="Internal validation error")
    finally:
        if tmp_dir:
            await asyncio.to_thread(shutil.rmtree, tmp_dir, ignore_errors=True)
