from pydantic import BaseModel


class PreviewRequest(BaseModel):
    job_id: str
    file_name: str
    converter_type: str  # "counseling" | "training"


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


class ConvertResponse(BaseModel):
    xml_path: str
    stats: dict
    xsd_valid: bool
    xsd_errors: list[str]
    issues: list[dict]
    cleaning_diff: list[dict]
