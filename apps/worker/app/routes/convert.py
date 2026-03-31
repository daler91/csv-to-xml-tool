import logging
import os
import tempfile

import aiofiles
from fastapi import APIRouter, HTTPException

from ..models.schemas import ConvertRequest, ConvertResponse
from ..services.conversion_service import run_conversion

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/convert",
    response_model=ConvertResponse,
    responses={
        404: {"description": "CSV file not found"},
        400: {"description": "Invalid request parameters"},
        500: {"description": "Internal conversion error"},
    },
)
async def convert(req: ConvertRequest):
    tmp_csv_path = None
    tmp_xml_path = None
    try:
        # Write streamed CSV content to a temp file
        fd_csv, tmp_csv_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd_csv)
        async with aiofiles.open(tmp_csv_path, mode="w", encoding="utf-8") as f:
            await f.write(req.file_content)

        # Create a temp file for XML output
        fd_xml, tmp_xml_path = tempfile.mkstemp(suffix=".xml")
        os.close(fd_xml)

        result = run_conversion(
            csv_path=tmp_csv_path,
            xml_path=tmp_xml_path,
            converter_type=req.converter_type,
            column_mapping=req.column_mapping,
        )

        # Read generated XML and include in response
        xml_content = None
        if os.path.exists(tmp_xml_path):
            async with aiofiles.open(tmp_xml_path, mode="r", encoding="utf-8") as f:
                xml_content = await f.read()

        result["xml_content"] = xml_content
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
    finally:
        if tmp_csv_path and os.path.exists(tmp_csv_path):
            os.unlink(tmp_csv_path)
        if tmp_xml_path and os.path.exists(tmp_xml_path):
            os.unlink(tmp_xml_path)
