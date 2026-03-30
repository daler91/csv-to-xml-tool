from pydantic import BaseModel


class PreviewRequest(BaseModel):
    csv_path: str
    converter_type: str  # "counseling" | "training"


class PreviewResponse(BaseModel):
    headers: list[str]
    rows: list[dict[str, str]]
    total_rows: int
    column_status: dict


class ConvertRequest(BaseModel):
    job_id: str
    csv_path: str
    converter_type: str
    column_mapping: dict[str, str] | None = None


class ConvertResponse(BaseModel):
    xml_path: str
    stats: dict
    xsd_valid: bool
    xsd_errors: list[str]
    issues: list[dict]
    cleaning_diff: list[dict]


class ValidateXsdRequest(BaseModel):
    xml_file_path: str
    schema_type: str  # "counseling" | "training"


class ValidateXsdResponse(BaseModel):
    is_valid: bool
    errors: list[str]
    error_count: int
