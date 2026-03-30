import logging
import os

from fastapi import APIRouter, HTTPException

from ..core.security import validate_path, safe_output_path
from ..models.schemas import ConvertRequest, ConvertResponse
from ..services.conversion_service import run_conversion

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/convert", response_model=ConvertResponse)
async def convert(req: ConvertRequest):
    try:
        # Validate input path stays within DATA_DIR
        csv_path = validate_path(req.csv_path)

        # Build validated output path within DATA_DIR
        xml_path = safe_output_path(req.job_id)

        result = run_conversion(
            csv_path=csv_path,
            xml_path=xml_path,
            converter_type=req.converter_type,
            column_mapping=req.column_mapping,
        )
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="CSV file not found")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request parameters")
    except Exception:
        logger.exception("Conversion failed")
        raise HTTPException(status_code=500, detail="Internal conversion error")
