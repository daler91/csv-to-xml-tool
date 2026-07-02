from pydantic import BaseModel


class PreviewRequest(BaseModel):
    job_id: str  # for log correlation only; the CSV travels in csv_content
    csv_content: str  # the uploaded CSV text, sent by the web (no shared volume)
    converter_type: str  # "counseling" | "training"


class PreviewResponse(BaseModel):
    headers: list[str]
    rows: list[dict[str, str]]
    total_rows: int
    column_status: dict
    # Feature 2.5: {"total_rows": int, "checks": [{"key", "label", "count",
    # "severity", "detail", "column"}]} — only checks with count > 0.
    data_quality: dict


class ConvertRequest(BaseModel):
    job_id: str  # for log correlation only; the CSV travels in csv_content
    csv_content: str  # the uploaded CSV text, sent by the web (no shared volume)
    converter_type: str
    column_mapping: dict[str, str] | None = None


class ConvertResponse(BaseModel):
    xml_content: str  # the converted XML text, returned to the web (no shared volume)
    stats: dict
    xsd_valid: bool
    xsd_errors: list[str]
    # Feature 2.4: structured detail per xsd_errors entry (empty when xsd_valid);
    # see src/xsd_error_mapping.py for the detail dict shape.
    xsd_error_details: list[dict]
    issues: list[dict]
    cleaning_diff: list[dict]


class ValidateXsdRequest(BaseModel):
    job_id: str  # for log correlation only; the XML travels in xml_content
    xml_content: str  # the XML text to validate, sent by the web (no shared volume)
    schema_type: str  # "counseling" | "training" | "training-client"


class ValidateXsdResponse(BaseModel):
    is_valid: bool
    errors: list[str]
    error_count: int
    # Feature 2.4: structured detail per errors entry (empty when is_valid);
    # row_number is the 1-based ordinal of the record element in the XML.
    error_details: list[dict]


class FixXmlRequest(BaseModel):
    job_id: str  # for log correlation only; the XML travels in xml_content
    xml_content: str  # the XML text to auto-fix, sent by the web (no shared volume)
    schema_type: str  # "counseling" | "training-client" (counseling-format XML only)


class FixXmlResponse(BaseModel):
    changed: bool  # whether the order-fix modified the document
    fixed_xml_content: str
    # Result of re-validating the fixed content against the counseling XSD:
    is_valid: bool
    errors: list[str]
    error_count: int
    error_details: list[dict]
