import logging
import os
import sys

from fastapi import APIRouter, HTTPException

from ..core.security import validate_path
from ..models.schemas import ValidateXsdRequest, ValidateXsdResponse

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


@router.post("/validate-xsd", response_model=ValidateXsdResponse)
async def validate_xsd(req: ValidateXsdRequest):
    xsd_file = os.path.join(SCHEMAS_DIR, XSD_MAP.get(req.schema_type, ""))
    if not os.path.exists(xsd_file):
        raise HTTPException(status_code=400, detail=f"Unknown schema type: {req.schema_type}")

    try:
        xml_path = validate_path(req.xml_file_path)
        result = validate_against_xsd(xml_path, xsd_file)
        is_valid = result.get("is_valid", False) if isinstance(result, dict) else bool(result)
        errors = result.get("errors", []) if isinstance(result, dict) else []
        return ValidateXsdResponse(
            is_valid=is_valid,
            errors=errors,
            error_count=len(errors),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("XSD validation failed")
        raise HTTPException(status_code=500, detail="Internal validation error")
