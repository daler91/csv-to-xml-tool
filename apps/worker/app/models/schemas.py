from pydantic import BaseModel


class PreviewRequest(BaseModel):
    job_id: str
    file_name: str
    converter_type: str  # "counseling" | "training"
    file_content: str  # CSV content streamed from web app


class PreviewResponse(BaseModel):
    headers: list[str]
    rows: list[dict[str, str]]
    total_rows: int
    column_status: dict


class ConvertRequest(BaseModel):
    job_id: str
    file_name: str
    converter_type: str
    column_mapping: dict[str, str] | None = None
    file_content: str  # CSV content streamed from web app


class ConvertResponse(BaseModel):
    xml_path: str
    xml_content: str | None = None  # XML content streamed back to web app
    stats: dict
    xsd_valid: bool
    xsd_errors: list[str]
    issues: list[dict]
    cleaning_diff: list[dict]
