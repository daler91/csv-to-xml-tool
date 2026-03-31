import logging
import os
import tempfile

from fastapi import APIRouter, HTTPException

from ..models.schemas import ConvertRequest, ConvertResponse
from ..services.conversion_service import run_conversion

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/convert", response_model=ConvertResponse)
async def convert(req: ConvertRequest):
    tmp_csv = None
    tmp_xml = None
    try:
        # Write streamed CSV content to a temp file
        tmp_csv = tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8"
        )
        tmp_csv.write(req.file_content)
        tmp_csv.close()

        # Create a temp file for XML output
        tmp_xml = tempfile.NamedTemporaryFile(
            suffix=".xml", delete=False
        )
        tmp_xml.close()

        result = run_conversion(
            csv_path=tmp_csv.name,
            xml_path=tmp_xml.name,
            converter_type=req.converter_type,
            column_mapping=req.column_mapping,
        )

        # Read generated XML and include in response
        xml_content = None
        if os.path.exists(tmp_xml.name):
            with open(tmp_xml.name, "r", encoding="utf-8") as f:
                xml_content = f.read()

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
