"""Wraps existing CSV-to-XML converters for use by the FastAPI service."""

import os
import sys
import tempfile
import pandas as pd

# Add the repo root's src/ to the Python path so we can import existing code
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.converters.counseling_converter import CounselingConverter
from src.converters.training_converter import TrainingConverter
from src.validation_report import ValidationTracker
from src.logging_util import ConversionLogger
from src.xml_validator import validate_against_xsd

from ..core.security import DATA_DIR

SCHEMAS_DIR = os.environ.get("SCHEMAS_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "..", "schemas"))

XSD_MAP = {
    "counseling": "SBA_NEXUS_Counseling-2-14.xsd",
    "training": "SBA_NEXUS_Training-2-25-2025.xsd",
}

CONVERTER_MAP = {
    "counseling": CounselingConverter,
    "training": TrainingConverter,
}


def run_conversion(
    csv_path: str,
    xml_path: str,
    converter_type: str,
    column_mapping: dict[str, str] | None = None,
) -> dict:
    """
    Run a CSV-to-XML conversion using the existing converter logic.

    All paths must be constructed and validated by the calling route.
    Returns a dict with stats, issues, xsd_valid, xsd_errors.
    """
    if converter_type not in CONVERTER_MAP:
        raise ValueError(f"Unknown converter type: {converter_type}")

    # Re-validate paths (CodeQL-recognized sanitizer: realpath + startswith guard)
    csv_path = os.path.realpath(csv_path)
    if not csv_path.startswith(DATA_DIR + os.sep):
        raise ValueError("csv_path is outside DATA_DIR")
    xml_path = os.path.realpath(xml_path)
    if not xml_path.startswith(DATA_DIR + os.sep):
        raise ValueError("xml_path is outside DATA_DIR")

    # Apply column mapping if provided (rename CSV columns before conversion)
    actual_csv_path = csv_path
    tmp_mapped = None
    if column_mapping:
        df = pd.read_csv(csv_path, dtype=str)
        df.rename(columns=column_mapping, inplace=True)
        tmp_mapped = tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, dir=os.path.dirname(csv_path)
        )
        df.to_csv(tmp_mapped.name, index=False)
        actual_csv_path = tmp_mapped.name

    try:
        # Set up logger and tracker
        logger = ConversionLogger(
            logger_name="WebConverter",
            log_to_file=False,
        )
        tracker = ValidationTracker()

        # Run conversion
        converter_cls = CONVERTER_MAP[converter_type]
        converter = converter_cls(logger, tracker)
        converter.convert(actual_csv_path, xml_path)

        # Validate against XSD
        xsd_file = os.path.join(SCHEMAS_DIR, XSD_MAP[converter_type])
        xsd_valid = False
        xsd_errors: list[str] = []
        if os.path.exists(xml_path) and os.path.exists(xsd_file):
            result = validate_against_xsd(xml_path, xsd_file)
            xsd_valid = result.get("is_valid", False)
            xsd_errors = result.get("errors", [])

        tracker_data = tracker.to_dict()
        summary = tracker_data["summary"]

        return {
            "xml_path": xml_path,
            "stats": {
                "total": summary["total_records"],
                "successful": summary["successful_records"],
                "errors": summary["error_count"],
                "warnings": summary["warning_count"],
            },
            "xsd_valid": xsd_valid,
            "xsd_errors": xsd_errors,
            "issues": tracker_data["issues"],
            "cleaning_diff": [],  # Populated by diff_service separately
        }
    finally:
        if tmp_mapped and os.path.exists(tmp_mapped.name):
            os.unlink(tmp_mapped.name)
