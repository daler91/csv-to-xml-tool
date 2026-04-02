import asyncio
import logging
import os
import tempfile

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
    tmp_csv = None
    tmp_xml = None
    try:
        # Write streamed CSV content to a temp file
        tmp_csv = await asyncio.to_thread(
            tempfile.NamedTemporaryFile,
            suffix=".csv", delete=False, mode="w", encoding="utf-8",
        )
        await asyncio.to_thread(tmp_csv.write, req.file_content)
        await asyncio.to_thread(tmp_csv.close)

        # Create a temp file for XML output
        tmp_xml = await asyncio.to_thread(
            tempfile.NamedTemporaryFile,
            suffix=".xml", delete=False,
        )
        await asyncio.to_thread(tmp_xml.close)

        result = await asyncio.to_thread(
            run_conversion,
            csv_path=tmp_csv.name,
            xml_path=tmp_xml.name,
            converter_type=req.converter_type,
            column_mapping=req.column_mapping,
        )

        # Read generated XML and include in response
        xml_content = None
        if await asyncio.to_thread(os.path.exists, tmp_xml.name):
            def _read_xml():
                with open(tmp_xml.name, "r", encoding="utf-8") as f:
                    return f.read()
            xml_content = await asyncio.to_thread(_read_xml)

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
        if tmp_csv and os.path.exists(tmp_csv.name):
            os.unlink(tmp_csv.name)
        if tmp_xml and os.path.exists(tmp_xml.name):
            os.unlink(tmp_xml.name)
