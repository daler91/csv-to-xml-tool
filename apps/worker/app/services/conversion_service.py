"""Wraps existing CSV-to-XML converters for use by the FastAPI service."""

import os
import sys
import tempfile
from typing import Callable, Optional
import pandas as pd

# Add the repo root's src/ to the Python path so we can import existing code
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.converters.counseling_converter import CounselingConverter
from src.converters.training_converter import TrainingConverter
from src.converters.training_client_converter import TrainingClientConverter
from src.converters.base_converter import EmptyCSVError
from src.validation_report import ValidationTracker
from src.logging_util import ConversionLogger
from src.xml_validator import validate_against_xsd
from src.config import ValidationCategory

from .cancellation import ConversionCancelledError
from .diff_service import generate_cleaning_diff
from .preview_service import get_expected_columns
from .column_requirements import (
    classify_columns,
    read_header_row,
    RequiredColumnsMissingError,
)

# Type alias mirroring BaseConverter.ProgressCallback so the worker
# service doesn't need to import from src/converters/.
ProgressCallback = Callable[[int, int], None]

SCHEMAS_DIR = os.environ.get("SCHEMAS_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "..", "schemas"))

XSD_MAP = {
    "counseling": "SBA_NEXUS_Counseling-2-14.xsd",
    "training": "SBA_NEXUS_Training-2-25-2025.xsd",
    "training-client": "SBA_NEXUS_Counseling-2-14.xsd",
}

CONVERTER_MAP = {
    "counseling": CounselingConverter,
    "training": TrainingConverter,
    "training-client": TrainingClientConverter,
}


def _sanitize_column_mapping(
    column_mapping: dict[str, str], converter_type: str
) -> dict[str, str]:
    """Drop mapping entries whose TARGET isn't a column the converter expects.

    The training mapping page once auto-suggested renaming a real header to an
    internal snake_case key (e.g. ``{"Class/Event ID": "event_id"}``); such an
    entry renames the source column out from under the converter, which then
    can't find it. A persisted bad mapping would keep breaking a job even after
    the suggestion bug is fixed, so we defensively ignore any entry whose target
    isn't a known expected column. A legitimate alias rename (target IS an
    expected header, e.g. ``{"Partner Organization": "Cosponsor"}``) is kept.
    """
    expected = set(get_expected_columns(converter_type))
    if not expected:
        # No expected-column list for this type; don't second-guess the mapping.
        return dict(column_mapping)
    return {src: dst for src, dst in column_mapping.items() if dst in expected}


def run_conversion(
    csv_path: str,
    xml_path: str,
    converter_type: str,
    column_mapping: dict[str, str] | None = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> dict:
    """
    Run a CSV-to-XML conversion using the existing converter logic.

    All paths must be constructed and validated by the calling route.
    Returns a dict with stats, issues, xsd_valid, xsd_errors.

    If ``is_cancelled`` is provided, it is polled at each major phase
    boundary. When it returns True, ``ConversionCancelledError`` is raised
    and the partial XML output is discarded. See
    ``apps/worker/app/services/cancellation.py`` for design notes.

    If ``on_progress`` is provided, it is installed as the converter's
    ``progress_callback`` and receives ``(processed, total)`` tuples
    roughly every 25 rows (counseling) or every 5 event groups
    (training). See UX_REVIEW.md §3.6.
    """
    if converter_type not in CONVERTER_MAP:
        raise ValueError(f"Unknown converter type: {converter_type}")

    def _checkpoint() -> None:
        if is_cancelled is not None and is_cancelled():
            raise ConversionCancelledError()

    # Early-exit before any work if the user cancelled before we got here.
    _checkpoint()

    # Apply column mapping if provided (rename CSV columns before conversion)
    actual_csv_path = csv_path
    tmp_mapped = None
    if column_mapping:
        # utf-8-sig so a BOM on the first header can't desync this rename from the
        # converter's own utf-8-sig read of the temp file written below (every
        # other CSV read path strips the BOM; this one was the lone exception).
        df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
        safe_mapping = _sanitize_column_mapping(column_mapping, converter_type)
        df.rename(columns=safe_mapping, inplace=True)
        tmp_mapped = tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, dir=os.path.dirname(csv_path)
        )
        df.to_csv(tmp_mapped.name, index=False)
        actual_csv_path = tmp_mapped.name

    _checkpoint()

    # Generate cleaning diff before conversion
    try:
        diffs = generate_cleaning_diff(actual_csv_path, converter_type)
    except Exception:
        diffs = []

    _checkpoint()

    try:
        # Set up logger and tracker
        logger = ConversionLogger(
            logger_name="WebConverter",
            log_to_file=False,
        )
        tracker = ValidationTracker()

        # CONV-1: validate the (post-mapping) header set before converting. A missing
        # required column hard-fails the job; missing conditional / fabrication-risk
        # columns become warnings so absent source data is never silently defaulted
        # into the federal XML.
        header = read_header_row(actual_csv_path)
        if len(header) != len(set(header)):
            # CONV-2: two columns collapsed to one name after whitespace
            # normalization; only the last is used. Surface it rather than
            # silently dropping a column.
            tracker.add_issue(
                "file",
                "warning",
                ValidationCategory.INVALID_FORMAT,
                "input_file",
                "Two or more columns share the same name after whitespace "
                "normalization; only the last occurrence was used.",
            )
        classification = classify_columns(header, converter_type)
        if classification["missing_required"]:
            raise RequiredColumnsMissingError(
                converter_type, classification["missing_required"]
            )
        for col in classification["missing_warn"]:
            tracker.add_issue(
                "file",
                "warning",
                ValidationCategory.MISSING_FIELD,
                col,
                f"Column '{col}' is absent; dependent values are left blank or "
                f"defaulted rather than taken from the source data.",
            )

        # Run conversion
        converter_cls = CONVERTER_MAP[converter_type]
        converter = converter_cls(logger, tracker)
        if on_progress is not None:
            converter.progress_callback = on_progress
        converter.convert(actual_csv_path, xml_path)

        _checkpoint()

        # Validate against XSD
        xsd_file = os.path.join(SCHEMAS_DIR, XSD_MAP[converter_type])
        xsd_valid = False
        xsd_errors: list[str] = []
        if os.path.exists(xml_path) and os.path.exists(xsd_file):
            result = validate_against_xsd(xml_path, xsd_file)
            xsd_valid = result.get("is_valid", False)
            xsd_errors = result.get("errors", [])

        _checkpoint()

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
            "cleaning_diff": diffs,
        }
    finally:
        if tmp_mapped and os.path.exists(tmp_mapped.name):
            os.unlink(tmp_mapped.name)
