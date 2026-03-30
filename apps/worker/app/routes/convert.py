import logging
import os

from fastapi import APIRouter, HTTPException

from ..core.security import validate_path
from ..models.schemas import ConvertRequest, ConvertResponse
from ..services.conversion_service import run_conversion

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/convert", response_model=ConvertResponse)
async def convert(req: ConvertRequest):
    try:
        # Validate input path stays within DATA_DIR
        csv_path = validate_path(req.csv_path)

        # Build output path within DATA_DIR
        output_dir = os.path.dirname(csv_path).replace("uploads", "output")
        os.makedirs(output_dir, exist_ok=True)
        xml_path = validate_path(os.path.join(output_dir, f"{req.job_id}.xml"))

        result = run_conversion(
            csv_path=csv_path,
            xml_path=xml_path,
            converter_type=req.converter_type,
            column_mapping=req.column_mapping,
        )
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="CSV file not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Conversion failed")
        raise HTTPException(status_code=500, detail="Internal conversion error")
