from fastapi import APIRouter, HTTPException

from ..models.schemas import PreviewRequest, PreviewResponse
from ..services.preview_service import read_csv_preview

router = APIRouter()


@router.post("/preview", response_model=PreviewResponse)
async def preview(req: PreviewRequest):
    try:
        result = read_csv_preview(req.csv_path, req.converter_type)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"CSV file not found: {req.csv_path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
