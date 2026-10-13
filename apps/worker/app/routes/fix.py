"""Auto-fix endpoint for counseling-format XML (feature 2.4).

Runs the element-order repair from src/xml_validator.py on the posted XML
content, re-validates the result against the counseling XSD, and returns
both the (possibly) fixed content and the structured validation outcome.
Order-fix only — missing elements are never added.
"""

import asyncio
import logging
import os
import sys

from fastapi import APIRouter, HTTPException

# Ensure src is importable
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.xml_validator import fix_element_order

from ..logging_context import set_job_id
from ..models.schemas import FixXmlRequest, FixXmlResponse
from ..services.xsd_validation import (
    cleanup_staging,
    read_text,
    stage_xml_content,
    validate_with_details,
)
from .validate import SCHEMAS_DIR, XSD_MAP

logger = logging.getLogger(__name__)

router = APIRouter()

# The fixer orders a document by the schema it is checked against here, the
# Form 641 one, which the training-client converter also emits. Training
# (Form 888) XML is not offered here.
_COUNSELING_FORMAT_SCHEMA_TYPES = {"counseling", "training-client"}


@router.post(
    "/fix-xml",
    response_model=FixXmlResponse,
    responses={
        400: {"description": "Unsupported schema type or empty XML content"},
        500: {"description": "Internal fix error"},
    },
)
async def fix_xml(req: FixXmlRequest):
    """Auto-fix element order and re-validate (Contract C).

    The web sends the XML text in the request body and gets the fixed text
    back — web and worker cannot share a volume. A document the fixer can't
    process (unparseable, entity declarations, ...) is a *result*
    (changed=false, fix_error saying why, is_valid=false with the
    validation errors), not a 500. job_id is for log correlation only.
    """
    set_job_id(req.job_id)

    if req.schema_type not in _COUNSELING_FORMAT_SCHEMA_TYPES:
        raise HTTPException(
            status_code=400, detail="auto-fix supports counseling-format XML only"
        )
    if not req.xml_content.strip():
        raise HTTPException(status_code=400, detail="xml_content must not be empty")

    xsd_file = os.path.join(SCHEMAS_DIR, XSD_MAP["counseling"])

    tmp_dir = None
    try:
        tmp_dir, input_path = await stage_xml_content("fix_", req.xml_content)
        fixed_path = os.path.join(tmp_dir, "fixed.xml")

        # Order-fix only: never add missing elements (add_missing_elements_flag
        # stays False, matching src/fix_sba_xml.py's original behavior). It
        # parses and serializes the whole document: CPU-bound, so off the
        # event loop like every other step here (about 10 s at 28 MB, during
        # which /health and every progress poll used to stall).
        result = await asyncio.to_thread(
            fix_element_order, input_path, fixed_path, False, xsd_file
        )
        if result.changed:
            fixed_content = await asyncio.to_thread(read_text, fixed_path)
            validate_path = fixed_path
        else:
            # Nothing moved, or the fixer could not read the document: hand
            # back exactly what was sent. `changed` used to compare two
            # reserializations, so a CR written as &#13; (which the old
            # fixer wrote back raw) read as a change when nothing had moved.
            fixed_content = req.xml_content
            validate_path = input_path

        validation = await validate_with_details(
            validate_path, xsd_file, "counseling"
        )
        return {
            "changed": result.changed,
            "fixed_xml_content": fixed_content,
            "fix_error": result.error,
            **validation,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("XML auto-fix failed")
        raise HTTPException(status_code=500, detail="Internal fix error") from e
    finally:
        await cleanup_staging(tmp_dir)
