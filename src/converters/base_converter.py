"""
Defines the base class for all data converters.

This module provides an abstract base class (ABC) that sets the common interface
for all converter implementations. Each converter must handle its own specific
logic for reading, processing, and writing data, but must conform to the
`convert` method signature defined here.
"""

from __future__ import annotations

import abc
import contextlib
import csv
import io
import logging
import os
from typing import TYPE_CHECKING, Callable, Optional

from .. import data_cleaning
from ..config import ValidationCategory
from ..schema_rules import schema_path, strip_illegal_xml_chars
from ..xml_utils import write_document
from ..xml_validator import validate_against_xsd
from ..xsd_error_mapping import errors_by_record

if TYPE_CHECKING:
    from ..validation_report import ValidationTracker

# Type alias for the progress callback signature.
# First int is rows processed so far, second is total rows.
ProgressCallback = Callable[[int, int], None]


class EmptyCSVError(ValueError):
    """Raised when an input CSV has headers but no data rows (CONV-6).

    Subclasses ValueError so existing ValueError handling still catches it; the
    worker maps it to HTTP 422 and the CLI exits non-zero, so an empty/headers-only
    CSV fails loudly instead of silently producing an empty federal XML.
    """


class BaseConverter(abc.ABC):
    """
    Abstract Base Class for all data converters.

    This class defines the standard interface for converters. It ensures that
    each converter is initialized with essential services like a logger and a
    validation tracker.
    """

    # The schema the output is filed against: "counseling", "training" or
    # "training-client" (see schema_rules.XSD_FILES).
    SCHEMA_TYPE = ""

    def __init__(self, logger: logging.Logger, validator: ValidationTracker) -> None:
        """
        Initializes the converter with a logger and a validator.

        Args:
            logger: An instance of a logger for logging messages.
            validator: An instance of ValidationTracker to track validation issues.
        """
        self.logger = logger
        self.validator = validator
        # Optional progress callback set by callers that want row-level
        # progress updates (e.g. the FastAPI worker, which polls this
        # back into an in-memory registry the web app reads to draw
        # the progress bar). None by default so the CLI path is
        # unchanged. See docs/reviews/UX_REVIEW.md §3.6.
        self.progress_callback: Optional[ProgressCallback] = None
        # Filled by convert(): for each record element, in document order,
        # {"row": the 1-based CSV data row it came from, "event": its event or
        # activity id, "columns": {element ("Parent/Tag" or "Tag"): the CSV
        # column that supplied it, where that differs by row}}. Passed to
        # xsd_error_mapping.build_error_details so XSD errors cite the user's
        # row, not the record's position in the XML.
        self.record_sources: list[dict] = []
        # Why each record left out of the file was (see _leave_out), in order.
        self.left_out_reasons: list[str] = []

    def _read_csv(self, input_path: str) -> tuple[list[str], list[dict]]:
        """Read the input CSV as (normalized headers, rows).

        Decodes the way the web upload does (data_cleaning.decode_csv_bytes),
        so a Windows-1252 export converts from the command line too instead of
        stopping at the first accented name, and keeps duplicate columns from
        erasing each other (data_cleaning.NormalizedDictReader). Both are
        recorded as file-level warnings. A file that cannot be read is
        recorded as a FILE_ACCESS error and re-raised.
        """
        try:
            with open(input_path, "rb") as csv_file:
                text, encoding = data_cleaning.decode_csv_bytes(csv_file.read())
            reader = data_cleaning.NormalizedDictReader(io.StringIO(text))
            rows = [self._blank_unwritable_cells(row) for row in reader]
        except (OSError, csv.Error) as e:
            self.logger.error(f"Failed to read CSV file: {e}")
            self._file_error(ValidationCategory.FILE_ACCESS, f"Failed to read CSV file: {e}")
            raise
        self.logger.info(f"Successfully read CSV file with {len(rows)} records")
        if encoding == "windows-1252":
            self.validator.add_issue(
                "file", "warning", ValidationCategory.FILE_ACCESS, "input_file",
                "The file is not UTF-8, so it was read as Windows-1252 (Excel's \"CSV (Comma "
                "delimited)\"). Check that accented names came through correctly.")
        for name, count in reader.duplicates.items():
            self.validator.add_issue("file", "warning", ValidationCategory.INVALID_FORMAT, name,
                                     data_cleaning.duplicate_header_message(name, count))
        return reader.fieldnames, rows

    @staticmethod
    def _blank_unwritable_cells(row: dict) -> dict:
        """Treat a cell holding only characters XML cannot carry as blank.

        SchemaGuard strips those characters from what is written, which left
        such a Contact ID as an empty <PartnerClientNumber/> -- valid XML that
        names nobody -- where a blank one leaves the row out with an error.
        Blanking the cell here gives every column its blank-cell handling.
        """
        for column, value in row.items():
            if value and not value.isspace() and not strip_illegal_xml_chars(value).strip():
                row[column] = ""
        return row

    def _file_error(self, category: str, message: str) -> None:
        """Record an error about the input file as a whole."""
        self.validator.add_issue("file", "error", category, "input_file", message)

    def _leave_out(self, root, record, why: str) -> None:
        """Remove a record element from the output, with its record_sources
        entry. Used for a record that cannot be filed -- one the schema guard
        found an unfixable required value in, one half built when an error
        stopped it, one the XSD still rejects -- so the rest of the file stays
        valid. `why` ("C-1, LocationCode: 'abc' is not a number") goes in
        left_out_reasons; the issue itself is the caller's to record."""
        records = [child for child in root if child.tag == record.tag]
        # The record being built is the last one; avoid the scan's cost for it.
        index = len(records) - 1 if records and records[-1] is record else records.index(record)
        root.remove(record)
        if index < len(self.record_sources):
            del self.record_sources[index]
        self.left_out_reasons.append(why)

    def _nothing_converted(self, what: str) -> EmptyCSVError:
        """Record that none of `what` ("3 row(s)") could be filed, and return
        the EmptyCSVError for the caller to raise: the schema needs at least one
        record. The web and the CLI show the error's message without the
        report, so it says why the first record was left out."""
        message = f"None of the {what} could be converted"
        if self.left_out_reasons:
            message += f"; the first was left out for {self.left_out_reasons[0].rstrip('.')}"
        self._file_error(ValidationCategory.MISSING_REQUIRED, message + ".")
        return EmptyCSVError(message + ".")

    def _write_valid_xml(self, root, output_path: str) -> int:
        """Write the document, then check it against SBA's XSD: the safety net
        under SchemaGuard, for anything it misses. A record that still fails is
        left out, with an error per XSD message naming its row, and the file is
        written again, so the file produced is one SBA accepts. Returns how many
        records were left out; raises EmptyCSVError when none is left. Without
        the XSD (a broken install) the file is only written; the worker reports
        a missing schema itself.
        """
        write_document(root, output_path)
        xsd = schema_path(self.SCHEMA_TYPE)
        if not os.path.exists(xsd):
            return 0
        result = validate_against_xsd(output_path, xsd)
        if result["is_valid"]:
            return 0
        failing = errors_by_record(output_path, result["errors"], self.SCHEMA_TYPE,
                                   self.record_sources)
        # Anything outside every record can't be fixed by leaving records out;
        # the worker's own validation reports it.
        if failing:
            total = len(root)
            self._leave_out_failing(root, failing)
            if len(root) == 0:
                with contextlib.suppress(OSError):
                    os.remove(output_path)
                raise self._nothing_converted(f"{total} record(s)")
            write_document(root, output_path)
        return len(failing)

    def _leave_out_failing(self, root, failing: dict[int, list[dict]]) -> None:
        """Leave out the records errors_by_record found failing, recording an
        error per XSD message against the row each came from."""
        self.logger.error(f"Left out {len(failing)} record(s) that failed XSD validation")
        # The root holds only records, in the order errors_by_record counts;
        # both lists are copied before _leave_out shortens them.
        records, sources = list(root), list(self.record_sources)
        for position in sorted(failing):
            event = sources[position - 1].get("event", "") if position <= len(sources) else ""
            for detail in failing[position]:
                self.validator.add_issue(
                    detail["record_id"] or f"Row_{detail['row_number']}", "error",
                    ValidationCategory.INVALID_VALUE,
                    detail["csv_column"] or detail["field_label"] or "record",
                    f"{detail['friendly_message']} SBA's schema rejects this, so the record was "
                    "left out of the XML; correct the value in the CSV and convert again.",
                    event_id=event)
            self._leave_out(root, records[position - 1], failing[position][0]["friendly_message"])
            self.validator.record_left_out()

    def _report_progress(self, processed: int, total: int) -> None:
        """Report progress to the callback if one is set. No-op otherwise."""
        if self.progress_callback is not None:
            try:
                self.progress_callback(processed, total)
            except Exception:  # noqa: BLE001 - never let progress errors break conversion
                # Progress reporting is best-effort. If the callback
                # raises (e.g. the registry was cleared while the
                # conversion was still running), swallow the error so
                # the conversion itself is unaffected.
                pass

    def _maybe_report_progress(
        self, processed: int, total: int, every: int = 25
    ) -> None:
        """Debounced progress report.

        Calls the callback roughly once every ``every`` rows so we
        don't hammer the registry on tiny files. Always reports the
        last row so the bar lands cleanly at the terminal count.
        """
        if processed == total or processed % every == 0:
            self._report_progress(processed, total)

    @abc.abstractmethod
    def convert(self, input_path: str, output_path: str) -> None:
        """
        Performs the data conversion.

        This method must be implemented by all subclasses. It should contain the
        core logic for reading the input file, processing the data, and writing
        the output file.

        Args:
            input_path: The full path to the input data file.
            output_path: The full path where the output file should be saved.

        Raises:
            NotImplementedError: If the subclass does not implement this method.
        """
        raise NotImplementedError("Each converter must implement the 'convert' method.")
