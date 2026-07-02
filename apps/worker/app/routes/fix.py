"""Auto-fix endpoint for counseling-format XML (feature 2.4).

Runs the ClientIntake element-order repair from src/xml_validator.py on the
posted XML content, re-validates the result against the counseling XSD, and
returns both the (possibly) fixed content and the structured validation
outcome. Order-fix only — missing elements are never added.
"""

import asyncio
import logging
import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

import defusedxml.ElementTree as SafeET
from fastapi import APIRouter, HTTPException

# Ensure src is importable
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.xml_validator import fix_client_intake_element_order, validate_against_xsd
from src.xsd_error_mapping import build_error_details

from ..logging_context import job_id_var
from ..models.schemas import FixXmlRequest, FixXmlResponse
from .validate import SCHEMAS_DIR, XSD_MAP

logger = logging.getLogger(__name__)

router = APIRouter()

# The order fixer only understands Form 641 counseling-format XML (which the
# training-client converter also emits); training (Form 888) XML has no
# ClientIntake section to repair.
_COUNSELING_FORMAT_SCHEMA_TYPES = {"counseling", "training-client"}


def _write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _canonical(xml_text: str) -> bytes | None:
    """Parsed-and-reserialized form of an XML document (None if unparseable).

    The fixer rewrites the file even when it moved nothing (declaration quoting
    and self-closing tags change), so raw text comparison would always report a
    change; comparing both sides through the same parse/serialize round-trip
    only differs when elements actually moved.
    """
    try:
        root = SafeET.fromstring(xml_text)
    except ET.ParseError:
        return None
    return ET.tostring(root)


@router.post(
    "/fix-xml",
    response_model=FixXmlResponse,
    responses={
        400: {"description": "Unsupported schema type or empty XML content"},
        500: {"description": "Internal fix error"},
    },
)
async def fix_xml(req: FixXmlRequest):
    """Auto-fix ClientIntake element order and re-validate (Contract C).

    The web sends the XML text in the request body and gets the fixed text
    back — web and worker cannot share a volume. Unparseable XML is a
    *result* (changed=false, is_valid=false with the parse error), not a 500.
    job_id is for log correlation only.
    """
    job_id_var.set(req.job_id)

    if req.schema_type not in _COUNSELING_FORMAT_SCHEMA_TYPES:
        raise HTTPException(
            status_code=400, detail="auto-fix supports counseling-format XML only"
        )
    if not req.xml_content.strip():
        raise HTTPException(status_code=400, detail="xml_content must not be empty")

    xsd_file = os.path.join(SCHEMAS_DIR, XSD_MAP["counseling"])

    tmp_dir = None
    try:
        # Stage the XML in a worker-local temp dir (same pattern as /validate-xsd).
        tmp_dir = await asyncio.to_thread(tempfile.mkdtemp, prefix="fix_")
        input_path = os.path.join(tmp_dir, "input.xml")
        fixed_path = os.path.join(tmp_dir, "fixed.xml")
        await asyncio.to_thread(_write_text, input_path, req.xml_content)

        # Order-fix only: never add missing elements (add_missing_elements_flag
        # stays False, matching src/fix_sba_xml.py's original behavior).
        fix_ok = await asyncio.to_thread(
            fix_client_intake_element_order, input_path, fixed_path, False
        )
        if fix_ok:
            fixed_content = await asyncio.to_thread(_read_text, fixed_path)
            changed = _canonical(req.xml_content) != _canonical(fixed_content)
            validate_path = fixed_path
        else:
            # Unparseable input (or fixer I/O failure): return the original
            # content unchanged and let validation surface the parse error.
            fixed_content = req.xml_content
            changed = False
            validate_path = input_path

        result = await asyncio.to_thread(validate_against_xsd, validate_path, xsd_file)
        errors = result.get("errors", [])
        is_valid = result.get("is_valid", False)
        error_details: list[dict] = []
        if not is_valid and errors:
            error_details = await asyncio.to_thread(
                build_error_details, validate_path, errors, "counseling"
            )
        return {
            "changed": changed,
            "fixed_xml_content": fixed_content,
            "is_valid": is_valid,
            "errors": errors,
            "error_count": len(errors),
            "error_details": error_details,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("XML auto-fix failed")
        raise HTTPException(status_code=500, detail="Internal fix error")
    finally:
        if tmp_dir:
            await asyncio.to_thread(shutil.rmtree, tmp_dir, ignore_errors=True)
