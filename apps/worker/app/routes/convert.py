import os

from fastapi import APIRouter, HTTPException

from ..models.schemas import ConvertRequest, ConvertResponse
from ..services.conversion_service import run_conversion

router = APIRouter()


@router.post("/convert", response_model=ConvertResponse)
async def convert(req: ConvertRequest):
    try:
        # Ensure output directory exists
        output_dir = os.path.dirname(req.csv_path).replace("uploads", "output")
        os.makedirs(output_dir, exist_ok=True)
        xml_path = os.path.join(output_dir, f"{req.job_id}.xml")

        result = run_conversion(
            csv_path=req.csv_path,
            xml_path=xml_path,
            converter_type=req.converter_type,
            column_mapping=req.column_mapping,
        )
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"CSV file not found: {req.csv_path}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
