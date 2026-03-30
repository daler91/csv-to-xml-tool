import logging
import os

from fastapi import APIRouter, HTTPException

from ..core.security import DATA_DIR, sanitize_id, sanitize_filename
from ..models.schemas import ConvertRequest, ConvertResponse
from ..services.conversion_service import run_conversion

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/convert", response_model=ConvertResponse)
async def convert(req: ConvertRequest):
    try:
        safe_id = sanitize_id(req.job_id)
        safe_name = sanitize_filename(req.file_name)

        # Construct and validate input path
        csv_path = os.path.realpath(os.path.join(DATA_DIR, "uploads", safe_id, safe_name))
        if not csv_path.startswith(DATA_DIR + os.sep):
            raise HTTPException(status_code=400, detail="Invalid path")

        # Construct and validate output path
        output_dir = os.path.realpath(os.path.join(DATA_DIR, "output", safe_id))
        if not output_dir.startswith(DATA_DIR + os.sep):
            raise HTTPException(status_code=400, detail="Invalid path")
        os.makedirs(output_dir, exist_ok=True)
        xml_path = os.path.join(output_dir, f"{safe_id}.xml")

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
    except HTTPException:
        raise
    except Exception:
        logger.exception("Conversion failed")
        raise HTTPException(status_code=500, detail="Internal conversion error")
