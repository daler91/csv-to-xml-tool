import logging
import os
import sys

from fastapi import APIRouter, HTTPException

from ..core.security import DATA_DIR, sanitize_id

# Ensure src is importable
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.xml_validator import validate_against_xsd

logger = logging.getLogger(__name__)

router = APIRouter()

SCHEMAS_DIR = os.environ.get("SCHEMAS_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "..", "schemas"))

XSD_MAP = {
    "counseling": "SBA_NEXUS_Counseling-2-14.xsd",
    "training": "SBA_NEXUS_Training-2-25-2025.xsd",
}


@router.post(
    "/validate-xsd",
    responses={
        400: {"description": "Invalid schema type or job ID"},
        500: {"description": "Internal validation error"},
    },
)
async def validate_xsd(job_id: str, schema_type: str):
    """Validate an already-converted XML file against its XSD schema."""
    xsd_file = os.path.join(SCHEMAS_DIR, XSD_MAP.get(schema_type, ""))
    if not os.path.exists(xsd_file):
        raise HTTPException(status_code=400, detail=f"Unknown schema type: {schema_type}")

    try:
        safe_id = sanitize_id(job_id)

        # Construct and validate path inline
        xml_path = os.path.realpath(os.path.join(DATA_DIR, "output", safe_id, f"{safe_id}.xml"))
        if not xml_path.startswith(DATA_DIR + os.sep):
            raise HTTPException(status_code=400, detail="Invalid path")

        result = validate_against_xsd(xml_path, xsd_file)
        is_valid = result.get("is_valid", False)
        errors = result.get("errors", [])
        return {
            "is_valid": is_valid,
            "errors": errors,
            "error_count": len(errors),
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID")
    except HTTPException:
        raise
    except Exception:
        logger.exception("XSD validation failed")
        raise HTTPException(status_code=500, detail="Internal validation error")
