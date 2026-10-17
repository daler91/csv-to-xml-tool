from typing import Literal

from pydantic import BaseModel, Field

# The three conversions the worker knows. A Literal, so an unknown value is a
# 422 from validation on every route: /preview used to accept "bogus" and
# answer 200 with an empty column status.
ConverterType = Literal["counseling", "training", "training-client"]


class PreviewRequest(BaseModel):
    job_id: str  # for log correlation only; the CSV travels in csv_content
    csv_content: str  # the uploaded CSV text, sent by the web (no shared volume)
    converter_type: ConverterType


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
    converter_type: ConverterType
    column_mapping: dict[str, str] | None = None
    # How the web had to read the upload before sending its text, named as
    # data_cleaning.decode_csv_bytes names it ("windows-1252", "utf-16 (odd
    # length)", ...), so the conversion records the file-level warning the
    # command line records. A str, not a Literal: a name this worker doesn't
    # know is no reason to fail a conversion; it just records no warning.
    source_encoding: str | None = Field(default=None, max_length=64)


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
    schema_type: ConverterType


class ValidateXsdResponse(BaseModel):
    is_valid: bool
    errors: list[str]
    error_count: int
    # Feature 2.4: structured detail per errors entry (empty when is_valid);
    # row_number is the 1-based ordinal of the record element in the XML (no
    # CSV here); conversion results cite the CSV data row instead.
    error_details: list[dict]


class FixXmlRequest(BaseModel):
    job_id: str  # for log correlation only; the XML travels in xml_content
    xml_content: str  # the XML text to auto-fix, sent by the web (no shared volume)
    # Any known type; the route answers "training" with a 400 that says
    # auto-fix supports counseling-format XML only.
    schema_type: ConverterType


class FixXmlResponse(BaseModel):
    changed: bool  # whether an element moved; nothing else is ever changed
    # The reordered document, or exactly the text sent when nothing moved.
    fixed_xml_content: str
    # Why the fixer could not process the document (unparseable, a DOCTYPE
    # that declares entities, ...); null when it ran. Lets the web say that,
    # rather than that the remaining errors are "in the data".
    fix_error: str | None = None
    # Result of re-validating the fixed content against the counseling XSD:
    is_valid: bool
    errors: list[str]
    error_count: int
    error_details: list[dict]
