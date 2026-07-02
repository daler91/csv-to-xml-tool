import logging
import os

from fastapi import APIRouter, HTTPException

from ..logging_context import job_id_var
from ..models.schemas import ValidateXsdRequest, ValidateXsdResponse
from ..services.xsd_validation import (
    cleanup_staging,
    stage_xml_content,
    validate_with_details,
)

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
        tmp_dir, xml_path = await stage_xml_content("validate_", req.xml_content)
        return await validate_with_details(xml_path, xsd_file, req.schema_type)
    except HTTPException:
        raise
    except Exception:
        logger.exception("XSD validation failed")
        raise HTTPException(status_code=500, detail="Internal validation error")
    finally:
        await cleanup_staging(tmp_dir)
