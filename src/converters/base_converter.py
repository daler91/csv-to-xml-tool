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
import copy
import csv
import io
import logging
import os
import re
from typing import TYPE_CHECKING, Callable, Optional

from .. import data_cleaning
from ..config import ValidationCategory
from ..schema_rules import clean_identifier, identifier_noise, schema_path
from ..xml_utils import ET, write_document
from ..xml_validator import VALIDATOR_GAVE_UP, XML_PARSE_ERROR, validate_against_xsd, validate_xml_content
from ..xsd_error_mapping import build_error_details, errors_by_record

if TYPE_CHECKING:
    from ..validation_report import ValidationTracker

# The reason given for a record the XSD check finds invalid without an error
# message to say why.
NO_REASON_GIVEN = "SBA's schema validator found this record invalid but gave no reason"

# What a record-level XSD error with no line means, by how its message begins.
# None of them is the schema rejecting a value, and none names a column, so
# each is worded as what happened.
_UNPLACED_ERRORS = (
    (VALIDATOR_GAVE_UP, "SBA's schema validator could not check a value in this record (it gives up "
                        "on some malformed values, most often an Email)"),
    (XML_PARSE_ERROR, "the record holds a character XML cannot carry"),
    (NO_REASON_GIVEN, NO_REASON_GIVEN),
)

# Whitespace to Python, which strips it, but control characters XML can't carry
# (or, U+0085, nobody can see): a vertical tab is a line break pasted from Word.
_CONTROL_WHITESPACE = re.compile("[\x0b\x0c\x1c-\x1f\x85]")

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
    # The columns holding identifiers, cleaned as they are read (see
    # _clean_identifiers); the first is the one that names the record.
    IDENTIFIER_COLUMNS: tuple[str, ...] = ()

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
        # True when the caller validates the file itself and shows its XSD
        # errors, as the worker does (xsd_errors): an XSD failure no record
        # explains is then not also recorded as a file error, which listed
        # the same messages twice on the results page.
        self.caller_reports_xsd_errors = False
        # (record, column, cell) for each identifier change already reported,
        # so an event's thirty attendee rows give one warning, not thirty.
        self._cleaned_identifiers: set[tuple[str, str, str]] = set()

    def _read_csv(self, input_path: str) -> tuple[list[str], list[dict]]:
        """Read the input CSV as (normalized headers, rows).

        Decodes the way the web upload does (data_cleaning.decode_csv_bytes),
        so a Windows-1252 export converts from the command line too instead of
        stopping at the first accented name, and keeps duplicate columns from
        erasing each other (data_cleaning.NormalizedDictReader). Both are
        recorded as file-level warnings, as are rows the reader saw lose data
        (see _report_row_shapes). A file that cannot be read is recorded as a
        FILE_ACCESS error and re-raised.
        """
        excel_errors: list[tuple[int, str, str]] = []
        unseen: list[tuple[int, str, str]] = []
        try:
            with open(input_path, "rb") as csv_file:
                text, encoding = data_cleaning.decode_csv_bytes(csv_file.read())
            reader = data_cleaning.NormalizedDictReader(io.StringIO(text))
            rows = [self._blank_unwritable_cells(row, number, excel_errors, unseen)
                    for number, row in enumerate(reader, 1)]
        except (OSError, csv.Error) as e:
            self.logger.error(f"Failed to read CSV file: {e}")
            self._file_error(ValidationCategory.FILE_ACCESS, f"Failed to read CSV file: {e}")
            raise
        self.logger.info(f"Successfully read CSV file with {len(rows)} records")
        message = data_cleaning.encoding_warning(encoding)
        if message:
            self.validator.add_issue("file", "warning", ValidationCategory.FILE_ACCESS, "input_file", message)
        for name, count in reader.duplicates.items():
            self.validator.add_issue("file", "warning", ValidationCategory.INVALID_FORMAT, name,
                                     data_cleaning.duplicate_header_message(name, count))
        self._report_row_shapes(reader)
        if excel_errors:
            number, column, value = excel_errors[0]
            self.validator.add_issue(
                "file", "warning", ValidationCategory.INVALID_VALUE, column,
                f"{len(excel_errors)} cell(s) hold an Excel error instead of a value, the first "
                f"'{value}' in row {number}; they were read as blank. Fix the formula in the "
                "spreadsheet if a value belongs there.")
        self._report_unseen_cells(unseen)
        return reader.fieldnames, rows

    def _report_unseen_cells(self, unseen: list[tuple[int, str, str]]) -> None:
        """One warning per column for the cells _blank_unwritable_cells read
        as blank for holding only characters nobody can see or read. A
        LocationCode of two control characters was filed as the default code,
        and nothing said why its cell counted as empty."""
        by_column: dict[str, list[tuple[int, str]]] = {}
        for number, column, value in unseen:
            by_column.setdefault(column, []).append((number, value))
        for column, cells in by_column.items():
            codes = sorted({f"U+{ord(ch):04X}" for _, value in cells for ch in value if ch not in " \t\n\r"})
            shown = ", ".join(codes[:5]) + (", ..." if len(codes) > 5 else "")
            if len(cells) == 1:
                where = f"Row {cells[0][0]}'s '{column}' cell holds"
            else:
                numbers = ", ".join(str(number) for number, _ in cells[:5]) + (", ..." if len(cells) > 5 else "")
                where = f"{len(cells)} '{column}' cells (rows {numbers}) hold"
            self.validator.add_issue(
                "file", "warning", ValidationCategory.INVALID_VALUE, column,
                f"{where} only invisible or unreadable characters ({shown}), so "
                f"{'it was' if len(cells) == 1 else 'they were'} read as blank. If a value belongs "
                "there, retype it in the spreadsheet.")

    def _report_row_shapes(self, reader) -> None:
        """Report the rows NormalizedDictReader saw lose data: a cell that
        swallowed the rows after it (each one an error, since whole rows are
        missing from the XML), and rows with values past the last column (one
        warning for the file, naming the first few)."""
        for number, column, lines in reader.swallowed_rows:
            self.validator.add_issue(
                "file", "error", ValidationCategory.INVALID_FORMAT, column,
                f"Row {number}'s '{column}' cell runs on over {lines} more line(s) that look like rows "
                "of their own: a quotation mark in it is probably opened and never closed. Those rows "
                "were read as part of the cell, so they are missing from the XML; close or remove the "
                "quotation mark and convert again.")
        if not reader.long_rows:
            return
        width = len(reader.fieldnames)
        if len(reader.long_rows) == 1:
            (number, extra), = reader.long_rows
            shown = ", ".join(f"'{value}'" for value in extra[:3]) + (", ..." if len(extra) > 3 else "")
            verb = "was" if len(extra) == 1 else "were"
            what = (f"Row {number} has more values than the header has columns ({width}): {shown} "
                    f"past the last column {verb} dropped, and its other values may be in the wrong "
                    "columns.")
        else:
            shown = ", ".join(str(number) for number, _ in reader.long_rows[:5])
            what = (f"{len(reader.long_rows)} rows have more values than the header has columns "
                    f"({width}): rows {shown}{', ...' if len(reader.long_rows) > 5 else ''}. Their "
                    "values past the last column were dropped, and their other values may be in "
                    "the wrong columns.")
        self.validator.add_issue("file", "warning", ValidationCategory.INVALID_FORMAT, "input_file",
                                 f"{what} Check for a comma that isn't inside quotes.")

    @staticmethod
    def _blank_unwritable_cells(row: dict, number: int, excel_errors: list, unseen: list) -> dict:
        """Treat a cell that holds no value as blank: one of only characters
        XML cannot carry, nobody can see, or that weren't text ('�'; see
        data_cleaning.is_blank_cell), or an Excel error such as '#N/A'. Each
        is appended, as (row, column, cell), to `excel_errors` or `unseen`,
        for the warnings _read_csv records.

        SchemaGuard strips the characters XML can't carry from what is written,
        which left such a Contact ID as an empty <PartnerClientNumber/> -- valid
        XML that names nobody; a zero-width space was filed as the ID itself,
        and '#N/A' as an event. Blanking the cell here gives every column its
        blank-cell handling, such as the error that leaves out a row without an ID.
        """
        for column, value in row.items():
            # Whitespace is left as it is: every reader already trims it. A
            # control character Python counts as whitespace is still reported.
            if (value and (not value.isspace() or _CONTROL_WHITESPACE.search(value))
                    and data_cleaning.is_blank_cell(value)):
                if data_cleaning.is_excel_error(value):
                    excel_errors.append((number, column, value.strip()))
                else:
                    unseen.append((number, column, value))
                row[column] = ""
        return row

    def _clean_identifiers(self, row: dict) -> list[tuple[str, str]]:
        """Clean the row's IDENTIFIER_COLUMNS in place to the form they are
        written in (schema_rules.clean_identifier); returns (column, the cell
        as written) for each one that changed, for _report_cleaned_identifiers
        once the row is known to be a record.

        A zero-width space at the end of a Contact ID was filed as part of it,
        and training grouped events on the raw ID, so 'EVT-001' with a control
        character was a second event that the schema guard then wrote as
        'EVT-001' too.
        """
        changed = []
        for column in self.IDENTIFIER_COLUMNS:
            raw = row.get(column)
            if raw and clean_identifier(raw) != raw.strip():
                row[column] = clean_identifier(raw)
                changed.append((column, raw))
        return changed

    def _report_cleaned_identifiers(self, changed: list[tuple[str, str]], record_id: str,
                                    event_id: str | None = None) -> None:
        """One warning per identifier _clean_identifiers changed, naming what it took out."""
        for column, raw in changed:
            if (record_id, column, raw) in self._cleaned_identifiers:
                continue
            self._cleaned_identifiers.add((record_id, column, raw))
            codes = identifier_noise(raw)
            what = "an invisible or control character" if len(codes) == 1 else \
                f"{len(codes)} invisible or control characters"
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.STANDARDIZED_VALUE, column,
                f"The {column} had {what} in it ({', '.join(codes)}), which would make it a different "
                f"ID from the one it looks like; filed as '{clean_identifier(raw)}'.",
                event_id=event_id)

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
        total, left_out = len(root), 0
        # Each pass leaves out at least one record or returns, and the file
        # is checked again after every rewrite.
        while True:
            result = validate_against_xsd(output_path, xsd)
            if result["is_valid"]:
                return left_out
            failing = errors_by_record(output_path, result["errors"], self.SCHEMA_TYPE,
                                       self.record_sources)
            if sum(map(len, failing.values())) < len(result["errors"]):
                # An error no record can be blamed for by its line: libxml2
                # giving up on a value, which also hides every other error in
                # the file. Each record is then checked on its own.
                failing = self._failing_records(root, xsd)
            if not failing:
                # Leaving records out can't fix it, so say so: the CLI shows
                # only this report.
                if not self.caller_reports_xsd_errors:
                    self._file_error(
                        ValidationCategory.PROCESSING_ERROR,
                        "The XML fails SBA's schema, and no record on its own does: "
                        + "; ".join(result["errors"][:3]))
                return left_out
            self._leave_out_failing(root, failing)
            left_out += len(failing)
            if len(root) == 0:
                with contextlib.suppress(OSError):
                    os.remove(output_path)
                raise self._nothing_converted(f"{total} record(s)")
            write_document(root, output_path)

    def _failing_records(self, root, xsd: str) -> dict[int, list[dict]]:
        """errors_by_record's result, found by validating each record alone
        in a copy of the root."""
        failing: dict[int, list[dict]] = {}
        for position, record in enumerate(root, 1):
            single = ET.Element(root.tag, root.attrib)
            single.append(copy.deepcopy(record))
            ET.indent(single, space="  ")
            content = ET.tostring(single, encoding="unicode")
            result = validate_xml_content(content.encode("utf-8"), xsd)
            if result["is_valid"]:
                continue
            sources = self.record_sources[position - 1:position]
            # Invalid with no message still leaves the record out, with a
            # reason: _leave_out_failing names each record by its first.
            details = build_error_details(content, result["errors"] or [NO_REASON_GIVEN],
                                          self.SCHEMA_TYPE, sources)
            row = sources[0].get("row") if sources else position
            record_id = (record[0].text or "").strip() if len(record) else None
            for detail in details:
                if detail["row_number"] is None:  # no line to place it by
                    detail.update(row_number=row, record_id=record_id,
                                  **self._unplaced_error(row, record_id, detail["message"]))
            failing[position] = details
        return failing

    def _unplaced_error(self, row: int, record_id: str | None, message: str) -> dict:
        """friendly_message for an error _failing_records can't place by its
        line, and whether it is the schema rejecting a value ("rejected"),
        which _leave_out_failing says. libxml2 giving up, or a character XML
        can't carry, was reported as "Row 2: SBA's schema validator could not
        finish checking this (...). SBA's schema rejects this", with no ID."""
        who = f"Row {row}"
        if record_id:
            column = self.IDENTIFIER_COLUMNS[0] if self.IDENTIFIER_COLUMNS else "ID"
            who += f" ({column} {record_id})"
        for start, what in _UNPLACED_ERRORS:
            if message.startswith(start):
                return {"friendly_message": f"{who}: {what}", "rejected": False}
        return {"friendly_message": f"{who}: {message}", "rejected": True}

    def _leave_out_failing(self, root, failing: dict[int, list[dict]]) -> None:
        """Leave out the records errors_by_record found failing, recording an
        error per XSD message against the row each came from."""
        self.logger.error(f"Left out {len(failing)} record(s) that failed XSD validation")
        # The root holds only records, in the order errors_by_record counts.
        records, sources = list(root), list(self.record_sources)
        for position in sorted(failing):
            event = sources[position - 1].get("event", "") if position <= len(sources) else ""
            for detail in failing[position]:
                why = " SBA's schema rejects this," if detail.get("rejected", True) else ","
                self.validator.add_issue(
                    detail["record_id"] or f"Row_{detail['row_number']}", "error",
                    ValidationCategory.INVALID_VALUE,
                    detail["csv_column"] or detail["field_label"] or "record",
                    f"{detail['friendly_message']}{why} so the record was left out of the XML; "
                    "correct the value in the CSV and convert again.",
                    event_id=event)
            self.left_out_reasons.append(failing[position][0]["friendly_message"])
            self.validator.record_left_out()
        # In one pass: _leave_out per record made 20,000 failing records take
        # 45 seconds.
        root[:] = [record for position, record in enumerate(records, 1) if position not in failing]
        self.record_sources[:] = [source for position, source in enumerate(sources, 1)
                                  if position not in failing]

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
