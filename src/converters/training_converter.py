"""
Handles the conversion of SBA Management Training Reports from CSV to XML.
"""

from .. import data_validation
import xml.etree.ElementTree as ET
import functools
import re
from collections import defaultdict
from typing import NamedTuple

from .base_converter import BaseConverter, EmptyCSVError
from ..config import TrainingConfig, GeneralConfig, ValidationCategory
from .. import data_cleaning
from ..schema_rules import SchemaGuard, _check_value
from ..xml_utils import create_element

# Cosponsor cells that say there was none.
_NO_COSPONSOR = frozenset({'', 'n/a', 'na', 'none', '-', 'null', 'n/a.'})

# How many of an event's differing values a warning lists.
_SHOWN_VALUES = 3

# A ZIP, or ZIP+4, anywhere in the cell ('IA 50010') but not inside a longer
# run of digits, where it is part of a phone number. The +4 may follow a
# hyphen or a dash with spaces around it, a space, or nothing (503091234, a
# ZIP+4 a spreadsheet stored as a number). [0-9], not \d: the XSD's \d, as
# libxml2 has it, is ASCII only.
_ZIP = re.compile(r'(?<![0-9])([0-9]{5})(?:(?:\s*[-\u2013\u2014]\s*|\s?)([0-9]{4}))?(?![0-9])')
# How Excel keeps a ZIP's leading zero: ="05030", or a leading apostrophe.
_EXCEL_TEXT = re.compile(r'="(.*)"|\'(.*)', re.S)


class _RowLocation(NamedTuple):
    """One row's City, State and ZIP, as read for TrainingLocation."""
    city: str
    state: str
    zip_code: str    # five digits, or '' when the cell has none
    zip4: str
    zip_cell: str    # the ZIP cell as written
    zip_header: str  # the file's column it came from
    zip_written: str  # the ZIP(+4) as the cell writes it
    ignored: bool    # whether the cell holds text besides it

class TrainingConverter(BaseConverter):
    """
    Converter for Management Training Report data.
    """
    SCHEMA_TYPE = "training"
    IDENTIFIER_COLUMNS = (TrainingConfig.COLUMN_MAPPING["event_id"],)

    # Read when the CSV has them, but not offered on the mapping page (which
    # lists TrainingConfig.COLUMN_MAPPING): optional, as on the counseling
    # form. Without a LocationCode every event is filed under
    # GeneralConfig.DEFAULT_LOCATION_CODE.
    _UNLISTED_COLUMNS = {"location_code": "LocationCode"}

    def __init__(self, logger, validator):
        super().__init__(logger, validator)
        self.config = TrainingConfig()
        self.general_config = GeneralConfig()
        self._schema_guard = SchemaGuard(self.SCHEMA_TYPE, validator, logger)
        self._first_rows = {}
        self._current_record = None
        self._headers = []

    # Event values the filing parses or SBA's schema checks: the method that
    # gives a value as it would be filed ('' when it can't be), and what such a
    # value is, for the warning when the event's rows disagree.
    _EVENT_VALUE_CHECKS = {
        'start_date': ('_filed_date', "a date this tool can read"),
        'funding_source': ('_funding_code', "a recognized SBA funding code"),
        'training_topic': ('_topic_code', "a recognized Training Topic"),
        'event_type': ('_program_format', "a recognized Class/Event Type"),
        'location_code': ('_location_code', "a location code SBA accepts"),
    }
    _LOCATION_CODE_PATH = ('ManagementTrainingReport', 'ManagementTrainingRecord', 'Location', 'LocationCode')

    def _column_value(self, record, key):
        """(header, value): the first of the key's columns that is filled in
        this row, and its value; (None, '') when none is. The header is the
        user's own, for an issue about the value."""
        possible_columns = self.config.COLUMN_MAPPING.get(key) or self._UNLISTED_COLUMNS.get(key, [])
        if isinstance(possible_columns, str):
            possible_columns = [possible_columns]

        for col in possible_columns:
            if col in record and not data_cleaning.is_empty(record[col]):
                return col, str(record[col])
        return None, ''

    def _get_column_value(self, record, key, default=''):
        """
        Gets a value from a row dict using the list of possible column names from config.
        """
        header, value = self._column_value(record, key)
        return value if header else default

    def _event_value(self, event_id, rows, key):
        """An event-level value, from whichever of the event's rows gives one.

        Every attendee row repeats the event's columns. Reading only the first
        row dropped a Funding Source or Cosponsor that only a later row had,
        and filed a fabricated default when the first row was blank. A value
        the filing parses or SBA's schema checks (_EVENT_VALUE_CHECKS) is taken
        from the first row where it is usable: a first row's 'TBD' LocationCode
        left the whole event out though the other rows gave a good one.

        Rows that disagree are reported, comparing values as they would be
        filed, so '1/15/2025' and '2025-01-15' agree. Only as many distinct
        values are kept as the warning lists: comparing each row with every
        value seen made a 20,000-row event take 20 seconds.
        """
        method, usable_as = self._EVENT_VALUE_CHECKS.get(key, (None, None))
        # value as written -> as filed, or '' when unusable; each distinct
        # value is checked once.
        filed_as = functools.cache(getattr(self, method) if method else str)
        shown = {}     # comparison key -> the value as first written
        first = filed = None  # (header, value)
        for header, value in self._event_cells(rows, key):
            first = first or (header, value)
            if filed is None and filed_as(value):
                filed = (header, value)
            if len(shown) <= _SHOWN_VALUES:
                shown.setdefault((filed_as(value) or value).casefold(), value)
            elif filed:
                break  # the value is found, and the warning can list no more
        if first is None:
            return ''
        header, value = filed or first
        if len(shown) > 1:
            self._report_event_disagreement(event_id, header, list(shown.values()),
                                            filed, first, usable_as)
        return value

    def _event_cells(self, rows, key):
        """(header, value) for each of the event's rows that fills `key`."""
        for row in rows:
            header, value = self._column_value(row, key)
            value = value.strip()
            if value:
                yield header, value

    def _report_event_disagreement(self, event_id, header, values, filed, first, usable_as):
        """Warn that an event's rows gave different `values` for a column,
        and which was filed: `filed`, the first usable, or none of them."""
        listed = ", ".join(f"'{v}'" for v in values[:_SHOWN_VALUES])
        if len(values) > _SHOWN_VALUES:
            listed += ", ..."
        value = (filed or first)[1]
        if filed is None:
            outcome = f"none of them is {usable_as}, so none was filed"
        elif filed == first:
            outcome = f"filed the first, '{value}'"
        else:
            outcome = f"filed '{value}', the first that is {usable_as}"
        self.validator.add_issue(
            str(event_id), "warning", ValidationCategory.INVALID_VALUE, header,
            f"The event's rows give different values for this column ({listed}); {outcome}.")

    def _header(self, key):
        """The CSV header to name in an issue about a COLUMN_MAPPING key: the
        first of its accepted spellings this file has, else the first
        configured. A file with 'Zip' was told about 'Zip/Postal Code'."""
        headers = self.config.COLUMN_MAPPING.get(key) or self._UNLISTED_COLUMNS.get(key, key)
        headers = [headers] if isinstance(headers, str) else headers
        return next((header for header in headers if header in self._headers), headers[0])

    def _read_and_validate_csv(self, input_path):
        """Read CSV, validate columns and rows. Returns (event_groups, event_id_col).

        ``event_groups`` is a list of ``(event_id, rows)`` pairs, sorted by event
        id. Raises EmptyCSVError when there is nothing convertible -- an empty
        CSV, a missing event-ID column, or no row carrying a usable event ID --
        so the caller can never write a success with no output file.
        """
        # CONV-2: the same read path the counseling converter uses. A short row
        # reads as blank cells, not None; it used to be pd.read_csv(dtype=str),
        # which made a blank cell float('nan') -- truthy, and the direct cause
        # of training rows passing validation and then vanishing in groupby().
        headers, rows = self._read_csv(input_path)
        self._headers = headers

        if not rows:
            # CONV-6: a headers-only / empty CSV must fail, not return silently.
            self.validator.add_issue("file", "error", ValidationCategory.MISSING_REQUIRED, "input_file", "CSV has headers but no data rows to convert.")
            raise EmptyCSVError("CSV has no data rows to convert.")

        event_id_col = self.config.COLUMN_MAPPING.get("event_id")
        if not event_id_col or event_id_col not in headers:
            self.logger.error(f"Required column '{event_id_col}' not found in the CSV.")
            self.validator.add_issue("file", "error", ValidationCategory.MISSING_REQUIRED, event_id_col, "Event ID column is missing.")
            raise EmptyCSVError(f"Required column '{event_id_col}' is missing from the CSV.")

        # 1-based, like the counseling converter's Row_N ids and row numbers.
        valid_rows = []
        for index, row in enumerate(rows, 1):
            # Before grouping: an ID the XML would write the same way as
            # another one is the same event.
            cleaned_ids = self._clean_identifiers(row)
            if data_validation.validate_training_record(row, index, self.validator):
                event_id = str(row[event_id_col]).strip()
                self._report_cleaned_identifiers(cleaned_ids, event_id, event_id=event_id)
                valid_rows.append((index, row))
        if not valid_rows:
            # Must raise, not return: a silent return left convert() writing no
            # file at all while main.py still logged "Conversion process
            # completed" and exited 0. Same contract as the empty-CSV case above.
            self.logger.error("No valid rows found in the CSV to process.")
            self.validator.add_issue("file", "error", ValidationCategory.MISSING_REQUIRED, event_id_col,
                                     "No rows had a usable Class/Event ID, so there is nothing to convert.")
            raise EmptyCSVError("No rows had a usable Class/Event ID to convert.")

        grouped = defaultdict(list)
        # The row each event's record cites in XSD errors: its first.
        self._first_rows = {}
        for index, row in valid_rows:
            # Trimmed: "EV1 " was filed as a second event beside "EV1".
            event_id = str(row[event_id_col]).strip()
            grouped[event_id].append(row)
            self._first_rows.setdefault(event_id, index)
        # sorted(), not insertion order: DataFrame.groupby defaults to
        # sort=True, so records have always been emitted ordered by event id.
        # Preserving that keeps the output byte-identical (see
        # tests/test_converter_characterization.py, which feeds deliberately
        # unsorted event ids).
        event_groups = [(event_id, grouped[event_id]) for event_id in sorted(grouped)]
        self.logger.info(f"Found {len(event_groups)} unique training events.")
        return event_groups, event_id_col

    def _warn_fabricated_default(self, event_id, field, default_value, element_label, raw=None):
        """Record a FABRICATED_DEFAULT warning for a value substituted for a blank cell.

        Mirrors CounselingConverter._warn_fabricated_default. Only for fields the
        CSV *could* have supplied -- deployment constants with no CSV source at
        all are reported once per file by _warn_constant_defaults instead, since
        a per-event warning for them would be identical every time.

        `raw` is the cell as written when it was filled but could not be used
        ('TBD' as a start date), so the message doesn't call it blank.
        """
        raw_text = str(raw).strip() if raw is not None else ''
        self.validator.add_issue(
            str(event_id), "warning", ValidationCategory.FABRICATED_DEFAULT, field,
            f"'{raw_text}' could not be used and was replaced with '{default_value}' ({element_label})."
            if raw_text else f"Blank value defaulted to '{default_value}' ({element_label}).",
        )

    def _warn_constant_defaults(self):
        """Record one file-level warning naming the values emitted from config.

        These have no CSV column behind them -- they are constants of this
        deployment that ship in every record of a federal filing. They are
        surfaced once so they are visible for audit without flooding the report
        with one identical warning per event.
        """
        constants = [
            ('Location/LocationCode', self.general_config.DEFAULT_LOCATION_CODE),
        ] if self._header('location_code') not in self._headers else [
            ('Location/LocationCode', f"{self.general_config.DEFAULT_LOCATION_CODE} "
                                      "(for events whose LocationCode cell is blank)"),
        ]
        constants += [
            ('NumberOfSessions', self.config.DEFAULT_TRAINING_SESSIONS),
            ('TotalTrainingHours', self.config.DEFAULT_TRAINING_HOURS),
            ('TrainingPartners/Code', self.config.DEFAULT_TRAINING_PARTNER_CODE),
            ('DollarAmountOfFees', self.config.DEFAULT_TRAINING_FEES),
            ('Language/Code', self.general_config.DEFAULT_LANGUAGE),
        ]
        self.validator.add_issue(
            "file", "warning", ValidationCategory.FABRICATED_DEFAULT, "configured_defaults",
            "Emitted from configuration for every record (no CSV column supplies them): "
            + "; ".join(f"{label}='{value}'" for label, value in constants)
            + ". Verify these match the reporting organization.",
            event_id="",
        )

    def _build_training_record(self, root, event_id, group_rows):
        """Build a single ManagementTrainingRecord element. Returns False when
        the record cannot be filed and was left out (see SchemaGuard.enforce)."""
        self.validator.set_current_record_id(str(event_id))
        self.validator.set_current_event_id(str(event_id))

        record = create_element(root, 'ManagementTrainingRecord')
        self._current_record = record
        self.record_sources.append({"row": self._first_rows.get(event_id), "event": str(event_id),
                                    "columns": {}})
        create_element(record, 'PartnerTrainingNumber', str(event_id))

        funding_source = self._event_value(event_id, group_rows, 'funding_source')
        if funding_source:
            valid_funding = self._resolve_funding_source(funding_source, event_id)
            if valid_funding:
                create_element(record, 'FundingSource', valid_funding)

        location = create_element(record, 'Location')
        # A LocationCode column is honoured, as the counseling forms do; the
        # schema guard leaves the event out if it isn't a code SBA accepts.
        create_element(location, 'LocationCode',
                       self._event_value(event_id, group_rows, 'location_code')
                       or self.general_config.DEFAULT_LOCATION_CODE)

        date_val = self._event_value(event_id, group_rows, "start_date")
        parsed_date = self._filed_date(date_val)
        formatted_date = parsed_date or self.config.DEFAULT_START_DATE
        if not parsed_date:
            # A blank or unparseable date silently becomes a fixed past date,
            # which is the kind of substitution a reviewer has to know about.
            self._warn_fabricated_default(event_id, 'Start Date', formatted_date, 'DateTrainingStarted',
                                          raw=date_val)
        create_element(record, 'DateTrainingStarted', formatted_date)
        if parsed_date and data_cleaning.has_zoned_time(date_val):
            # As CounselingConverter._warn_zoned_time: a UTC Date/Time from the
            # API is filed with its UTC date, which an evening event in the US
            # has already moved on to the next day.
            self.validator.add_issue(
                str(event_id), "warning", ValidationCategory.AMBIGUOUS_DATE, self._header('start_date'),
                f"'{date_val}' is a time in UTC or at a time-zone offset, so it was filed as "
                f"{formatted_date}, the date there, which can be a day later than the local date of the session.")
        if data_cleaning.is_ambiguous_date(date_val):
            # CONV-3: emitted month-first, but flag the ambiguity for human review.
            self.validator.add_issue(
                str(event_id), "warning", ValidationCategory.AMBIGUOUS_DATE,
                "DateTrainingStarted",
                f"Start date '{str(date_val).strip()}' is ambiguous between MM/DD "
                f"and DD/MM; interpreted month-first as {formatted_date}.",
            )

        create_element(record, 'NumberOfSessions', self.config.DEFAULT_TRAINING_SESSIONS)
        create_element(record, 'TotalTrainingHours', self.config.DEFAULT_TRAINING_HOURS)

        title_val = self._event_value(event_id, group_rows, "event_name")
        if not title_val:
            title_val = f"{self.config.DEFAULT_TRAINING_EVENT_TITLE_PREFIX}{event_id}"
            self._warn_fabricated_default(event_id, 'Class/Event Name', title_val, 'TrainingTitle')
        create_element(record, 'TrainingTitle', title_val)

        self._build_location_section(record, group_rows)
        demographics = self._calculate_demographics(group_rows)
        self._build_demographics_section(record, demographics)

        topic_val = self._event_value(event_id, group_rows, "training_topic")
        mapped_topic = self._resolve_training_topic(topic_val, event_id)
        training_topic_element = create_element(record, 'TrainingTopic')
        create_element(training_topic_element, 'Code', mapped_topic)

        partners_element = create_element(record, 'TrainingPartners')
        create_element(partners_element, 'Code', self.config.DEFAULT_TRAINING_PARTNER_CODE)

        format_val = self._event_value(event_id, group_rows, "event_type")
        create_element(record, 'ProgramFormatType', self._resolve_program_format(format_val, event_id))

        create_element(record, 'DollarAmountOfFees', self.config.DEFAULT_TRAINING_FEES)
        language_element = create_element(record, 'Language')
        create_element(language_element, 'Code', self.general_config.DEFAULT_LANGUAGE)

        # "N/A", "None" or "-" in the column means there was no cosponsor.
        cosponsor_rows = [row for row in group_rows
                          if (self._get_column_value(row, "cosponsor") or '').strip().casefold()
                          not in _NO_COSPONSOR]
        cosponsor_name = self._event_value(event_id, cosponsor_rows, "cosponsor")
        if cosponsor_name:
            create_element(record, 'CosponsorsName', cosponsor_name)

        # Last, on the finished record: lengths, enumerations, patterns and
        # ranges straight from the XSD (see src/schema_rules.py).
        unfileable = self._schema_guard.enforce(record, str(event_id), (root.tag,))
        if unfileable:
            # A required value no fix can make valid, such as a Class/Event ID
            # over 20 characters; the guard recorded why. Filing it would make
            # SBA reject the whole file.
            self._leave_out(root, record, f"{event_id}, {unfileable[0]}")
            return False
        return True

    def convert(self, input_path: str, output_path: str):
        self.logger.info(f"Starting conversion of training data: {input_path}")
        self.record_sources = []
        self.left_out_reasons = []

        event_groups, event_id_col = self._read_and_validate_csv(input_path)

        root = ET.Element('ManagementTrainingReport')
        root.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')

        # Recorded once up front, before any per-event event-id context is set.
        self._warn_constant_defaults()

        # Training converter aggregates per event, so "progress" is
        # measured in event groups rather than CSV rows. Call the
        # callback every N groups so the web progress bar advances.
        total_events = len(event_groups)
        self._report_progress(0, total_events)

        for i, (event_id, group_rows) in enumerate(event_groups, 1):
            if not group_rows:
                self._maybe_report_progress(i, total_events, every=5)
                continue
            self._current_record = None
            try:
                filed = self._build_training_record(root, event_id, group_rows)
                self.validator.record_processed(success=filed)
            except (ValueError, KeyError, AttributeError) as e:
                self.logger.error(f"Error processing event {event_id}: {e}", exc_info=True)
                self.validator.add_issue(str(event_id), "error", ValidationCategory.PROCESSING_ERROR, "record", f"Error processing event: {e}", event_id=str(event_id))
                if self._current_record is not None:
                    # Half built, so never valid; the error above explains it.
                    self._leave_out(root, self._current_record,
                                    f"{event_id}: an error while converting it ({e})")
                self.validator.record_processed(success=False)

            self._maybe_report_progress(i, total_events, every=5)

        self._report_progress(total_events, total_events)

        # File-level issues below must not inherit the last event's id.
        self.validator.set_current_event_id(None)

        if len(root) == 0:
            # Every event was left out: the schema needs at least one
            # ManagementTrainingRecord, so fail like an empty CSV does.
            raise self._nothing_converted(f"{total_events} event(s)")

        self._write_valid_xml(root, output_path)
        self.logger.info(f"XML file successfully created at {output_path}")

    def _location(self, row):
        """One row's City, State and ZIP (see _RowLocation). The ZIP is read
        from inside Excel's ="05030" or '05030, which keep its leading zero,
        and from anywhere in the cell, but never from a longer run of digits:
        taking the first five digits of a cell filed a phone number's as the
        ZIP."""
        zip_header, zip_cell = self._column_value(row, 'zip')
        zip_cell = zip_cell.strip()
        excel = _EXCEL_TEXT.fullmatch(zip_cell)
        text = next(part for part in excel.groups() if part is not None).strip() if excel else zip_cell
        zip_match = _ZIP.search(text)
        return _RowLocation(
            city=(self._get_column_value(row, 'city') or '').strip(),
            state=(self._get_column_value(row, 'state') or '').strip(),
            zip_code=zip_match.group(1) if zip_match else '',
            zip4=(zip_match.group(2) or '') if zip_match else '',
            zip_cell=zip_cell,
            zip_header=zip_header or self._header('zip'),
            zip_written=zip_match.group(0) if zip_match else '',
            ignored=bool(zip_match and (text[:zip_match.start()] + text[zip_match.end():]).strip()),
        )

    def _build_location_section(self, parent, rows):
        training_location = create_element(parent, 'TrainingLocation')
        event_id = str(self.validator.current_record_id)
        loc, given = self._event_location(rows)
        if loc is None:
            loc = self._default_location(event_id, given)
        else:
            self._report_location_zip(event_id, loc)

        create_element(training_location, 'City', loc.city)
        create_element(training_location, 'State', data_cleaning.standardize_state_name(loc.state))
        if loc.zip_code:
            create_element(training_location, 'ZipCode', loc.zip_code)
        if loc.zip4:
            create_element(training_location, 'Zip4Code', loc.zip4)
        country_element = create_element(training_location, 'Country')
        create_element(country_element, 'Code', self.config.DEFAULT_LOCATION['country'])

    def _event_location(self, rows):
        """(the row location to file or None, the first row giving any part).

        The first row with a city, a state and a ZIP; else the first with a
        city and a state, filed without a ZIP (ZipCode is optional) rather
        than replaced, city and state too, by the configured location.
        Reading only the first row filed a default when it alone was
        incomplete. Rows that give different addresses are not reported: in
        a campaign-member export each row's City/State/Zip is that
        attendee's own mailing address, so they differ on nearly every event.
        """
        partial = given = None
        for row in rows:
            loc = self._location(row)
            given = given or (loc if loc.city or loc.state or loc.zip_cell else None)
            if loc.city and loc.state and loc.zip_code:
                return loc, given
            if loc.city and loc.state:
                partial = partial or loc
        return partial, given

    def _default_location(self, event_id, given):
        """The configured location, filed for an event with no row giving a
        city and a state, and the warning that says so."""
        self.logger.info(f"Using default location for event {event_id}")
        default = self.config.DEFAULT_LOCATION
        where = f"{default['city']}, {default['state']} {default['zip']}"
        if given is None:
            self._warn_fabricated_default(event_id, 'Class/Event Location', where,
                                          'TrainingLocation; no row gives a city, state or ZIP')
        else:
            parts = ", ".join(f"{self._header(key)} '{value}'" if value else f"{self._header(key)} blank"
                              for key, value in (('city', given.city), ('state', given.state),
                                                 ('zip', given.zip_cell)))
            self.validator.add_issue(
                event_id, "warning", ValidationCategory.FABRICATED_DEFAULT, 'Class/Event Location',
                f"No row gives both a city and a state (the first to give any of them has {parts}), "
                f"so the configured location '{where}' was filed instead.")
        return _RowLocation(default['city'], default['state'], default['zip'], '', '', '', '', False)

    def _report_location_zip(self, event_id, loc):
        """Warn when the filed location's ZIP is missing, unreadable, or only
        part of its cell."""
        if loc.zip_code and loc.ignored:
            # As counseling's _build_address says it.
            self.validator.add_issue(
                event_id, "warning", ValidationCategory.INVALID_FORMAT, loc.zip_header,
                f"Only '{loc.zip_written}' of '{loc.zip_cell}' is a ZIP or ZIP+4, so the rest was left "
                "out of the XML.")
        elif loc.zip_code:
            return
        elif loc.zip_cell:
            self.validator.add_issue(
                event_id, "warning", ValidationCategory.INVALID_FORMAT, loc.zip_header,
                f"Could not read a 5-digit ZIP from '{loc.zip_cell}', so the location was filed "
                f"as '{loc.city}, {loc.state}' without one.")
        else:
            self.validator.add_issue(
                event_id, "warning", ValidationCategory.MISSING_FIELD, loc.zip_header,
                f"No ZIP code is given with '{loc.city}, {loc.state}', so the location was filed "
                "without one.")

    def _resolve_column(self, rows, column_key):
        """Resolve a config column key to the actual CSV column name present in the rows."""
        possible = self.config.COLUMN_MAPPING.get(column_key, [])
        if isinstance(possible, str):
            possible = [possible]
        return next((c for c in possible if any(c in row for row in rows)), None)

    def _demographic_rows(self, rows):
        """Each row's demographic answers under one key per COLUMN_MAPPING key,
        from the first of the key's columns that is filled *in that row*: with
        both "Gender" and "Sex" columns, a row with only "Sex" filled used to be
        counted from its blank "Gender"."""
        keys = ('business_status', 'gender', 'disability', 'military_status', 'race', 'ethnicity')
        present = {key for key in keys if self._resolve_column(rows, key)}
        return [{key: self._get_column_value(row, key) for key in present} for row in rows]

    def _filed_date(self, date_val):
        """The start date as YYYY-MM-DD, or '' when it doesn't parse."""
        return data_cleaning.format_date(date_val, self.config.DATE_INPUT_FORMATS)

    def _location_code(self, value):
        """The LocationCode as SBA's schema reads it ('249003.0' is 249003),
        or '' when the schema guard would refuse it and leave the event out."""
        rule = self._schema_guard.rules.get(self._LOCATION_CODE_PATH)
        if rule is None:  # schema facets unavailable; the final XSD check judges it
            return data_cleaning.clean_numeric(value)
        text, problem = _check_value(value, rule)
        return '' if problem else (data_cleaning.clean_numeric(text) or text)

    def _funding_code(self, funding_source):
        """The SBA funding code a Funding Source names, in the schema's
        spelling, or None."""
        cleaned = str(funding_source).strip().lower()
        return next((valid for valid in self.config.VALID_FUNDING_SOURCES if valid.lower() == cleaned), None)

    def _topic_code(self, topic_val):
        """The TrainingTopic/Code a Training Topic names or translates to, or None."""
        cleaned = str(topic_val).strip() if topic_val else ''
        if not cleaned:
            return None
        for valid_topic in self.config.VALID_TRAINING_TOPICS:
            if valid_topic.lower() == cleaned.lower():
                return valid_topic
        return data_cleaning.map_value(cleaned, self.config.TRAINING_TOPIC_MAPPINGS, None, False)

    def _program_format(self, format_val):
        """The ProgramFormatType a Class/Event Type maps onto, or None."""
        cleaned = str(format_val).strip() if format_val else ''
        return data_cleaning.map_value(cleaned, self.config.PROGRAM_FORMAT_MAPPINGS, None, False) if cleaned else None

    def _resolve_funding_source(self, funding_source, event_id):
        """Return the funding source iff it is a valid XSD enumeration value, else None.

        FundingSource is optional; a non-enumerated label (e.g. a WBC "CORE"/"Federal"
        funding string) must be omitted rather than emitted, or the XML fails schema
        validation. Unrecognized values are flagged for review.
        """
        valid_source = self._funding_code(funding_source)
        if valid_source:
            return valid_source
        self.validator.add_issue(
            str(event_id), "warning", ValidationCategory.INVALID_VALUE, "Funding Source",
            f"Funding Source '{str(funding_source).strip()}' is not a recognized SBA funding code; "
            "omitted from the XML.",
        )
        return None

    def _resolve_training_topic(self, topic_val, event_id):
        """Resolve a CSV Training Topic to a valid XSD TrainingTopic/Code.

        A value already in the SBA controlled vocabulary is returned verbatim (so a
        populated "Training Topic" column is authoritative); otherwise a known synonym
        is translated. An empty or unrecognized value falls back to the default,
        and both are recorded -- the blank case is the common one.
        """
        cleaned = str(topic_val).strip() if topic_val else ''
        if not cleaned:
            self._warn_fabricated_default(event_id, 'Training Topic', self.config.DEFAULT_TRAINING_TOPIC,
                                          'TrainingTopic/Code')
            return self.config.DEFAULT_TRAINING_TOPIC
        mapped = self._topic_code(cleaned)
        if mapped:
            return mapped
        self.validator.add_issue(
            str(event_id), "warning", ValidationCategory.INVALID_VALUE, "Training Topic",
            f"Unrecognized Training Topic '{cleaned}'; defaulted to '{self.config.DEFAULT_TRAINING_TOPIC}'.",
        )
        return self.config.DEFAULT_TRAINING_TOPIC

    def _resolve_program_format(self, format_val, event_id):
        """Map Class/Event Type onto ProgramFormatType. A blank or unrecognized
        value falls back to the default -- recorded, like the training topic,
        rather than turning "Workshop" into "In-person" silently."""
        default = self.config.DEFAULT_PROGRAM_FORMAT
        cleaned = str(format_val).strip() if format_val else ''
        if not cleaned:
            self._warn_fabricated_default(event_id, 'Class/Event Type', default, 'ProgramFormatType')
            return default
        mapped = self._program_format(cleaned)
        if mapped:
            return mapped
        self.validator.add_issue(
            str(event_id), "warning", ValidationCategory.INVALID_VALUE, "Class/Event Type",
            f"Unrecognized Class/Event Type '{cleaned}'; recorded as '{default}'.",
        )
        return default

    @staticmethod
    def _count_sex(rows, gender_col):
        """Return (female, male). Anything that maps to neither is counted as neither."""
        female = male = 0
        if not gender_col:
            return female, male
        for row in rows:
            sex = data_cleaning.map_gender_to_sex(row.get(gender_col))
            if sex == 'Female':
                female += 1
            elif sex == 'Male':
                male += 1
        return female, male

    @staticmethod
    def _count_business_status(rows, business_col):
        """Return (currently_in_business, not_in_business).

        Deliberately not `not is_affirmative`: a blank or unrecognised answer
        must land in neither bucket rather than being reported as "not yet in
        business" to SBA.
        """
        currently = not_yet = 0
        if not business_col:
            return currently, not_yet
        for row in rows:
            value = row.get(business_col)
            if data_cleaning.is_affirmative(value):
                currently += 1
            elif data_cleaning.is_negative(value):
                not_yet += 1
        return currently, not_yet

    @staticmethod
    def _count_disabilities(rows, disability_col):
        if not disability_col:
            return 0
        return sum(
            1 for row in rows
            if data_cleaning.is_affirmative(row.get(disability_col))
        )

    @staticmethod
    def _count_military(rows, military_col, military_keywords):
        """Count per category. A row may match several (e.g. service-disabled veteran)."""
        counts = {key: 0 for key in military_keywords}
        if not military_col:
            return counts
        for row in rows:
            for category in data_cleaning.classify_military(row.get(military_col), military_keywords):
                counts[category] += 1
        return counts

    @staticmethod
    def _count_race_ethnicity(rows, race_col, ethnicity_col, race_keywords):
        """Return (race_counts, hispanic, non_hispanic, minorities).

        Race, ethnicity and the minority tally share one pass because
        "minority" is a per-person question that depends on both.
        """
        race_counts = {key: 0 for key in race_keywords}
        hispanic = non_hispanic = minorities = 0

        for row in rows:
            person_races = (
                data_cleaning.classify_races(row.get(race_col), race_keywords)
                if race_col else set()
            )
            for category in person_races:
                race_counts[category] += 1

            person_ethnicity = (
                data_cleaning.classify_ethnicity(row.get(ethnicity_col))
                if ethnicity_col else None
            )
            if person_ethnicity == 'hispanic':
                hispanic += 1
            elif person_ethnicity == 'non_hispanic':
                non_hispanic += 1

            # Underserved/minority = distinct attendees who are Hispanic OR any non-white
            # race, counted per person (not a sum of category counts) so a multi-race
            # attendee is never double-counted.
            if person_ethnicity == 'hispanic' or any(c != 'white' for c in person_races):
                minorities += 1

        return race_counts, hispanic, non_hispanic, minorities

    def _report_uncounted(self, rows, race_col, military_col):
        """One warning per event for the Race and Military Status answers no
        count takes, naming them: "Two or More Races" or "Retired" left the
        attendee out of every race or military count without a word. Answers
        that decline the question, or say there was no military service,
        belong in no count and are not reported."""
        race_keywords = self.config.DEMOGRAPHIC_KEYWORDS['race']
        military_keywords = self.config.DEMOGRAPHIC_KEYWORDS['military']
        races = [label for row in rows if race_col
                 for label in data_cleaning.split_multi_value(row.get(race_col))
                 if not data_cleaning.classify_races(label, race_keywords)
                 and data_cleaning.classify_race_label(label)[0] != data_cleaning.RACE_PREFER_NOT_TO_SAY]
        statuses = [row.get(military_col).strip() for row in rows if military_col
                    and not data_cleaning.is_empty(row.get(military_col))
                    and not data_cleaning.classify_military(row.get(military_col), military_keywords)
                    and not data_cleaning.map_military_status_to_xsd(row.get(military_col))]
        event_id = str(self.validator.current_record_id)
        for key, answers, counts in (('race', races, "race"), ('military_status', statuses, "military")):
            if not answers:
                continue
            shown = ", ".join(f"'{answer}'" for answer in dict.fromkeys(answers))
            self.validator.add_issue(
                event_id, "warning", ValidationCategory.INVALID_VALUE, self._header(key),
                f"{shown} {'fits' if len(set(answers)) == 1 else 'fit'} none of SBA's {counts} counts, "
                f"so {len(answers)} attendee answer{'s were' if len(answers) != 1 else ' was'} "
                f"counted under no {counts} category.")

    def _calculate_demographics(self, rows):
        """Aggregate per-attendee rows for one event into demographic counts.

        Each attendee row is classified by its controlled-vocabulary value (reusing
        data_cleaning helpers) instead of loose substring matching, so "Prefer not to
        say"/blank fall into no bucket, "Female" is never miscounted as Male, and "Non
        Hispanic or Latino" is never miscounted as Hispanic.

        The per-dimension tallies live in the _count_* helpers above; this method
        resolves the columns and assembles the result. Each helper walks `rows`
        separately, which is a handful of passes over one event's attendee list --
        not worth folding back into a single unreadable loop.
        """
        race_keywords = self.config.DEMOGRAPHIC_KEYWORDS['race']
        military_keywords = self.config.DEMOGRAPHIC_KEYWORDS['military']
        rows = self._demographic_rows(rows)

        # Keyed by COLUMN_MAPPING key now; None where no column is present.
        def column(key):
            return key if rows and key in rows[0] else None

        business_col = column('business_status')
        self._report_uncounted(rows, column('race'), column('military_status'))
        female, male = self._count_sex(rows, column('gender'))
        currently_in_business, not_in_business = self._count_business_status(rows, business_col)
        military_counts = self._count_military(rows, column('military_status'), military_keywords)
        race_counts, hispanic, non_hispanic, minorities = self._count_race_ethnicity(
            rows, column('race'), column('ethnicity'), race_keywords,
        )

        demographics = {
            'total': max(len(rows), 1),  # XSD requires Total >= 1
            'female': female,
            'male': male,
            'disabilities': self._count_disabilities(rows, column('disability')),
            'active_duty': military_counts.get('active_duty', 0),
            'veterans': military_counts.get('veteran', 0),
            'service_disabled_veterans': military_counts.get('service_disabled_veteran', 0),
            'reserve_guard': military_counts.get('reserve_guard', 0),
            'military_spouse': military_counts.get('spouse', 0),
            'race': race_counts,
            'ethnicity': {'hispanic': hispanic, 'non_hispanic': non_hispanic},
            'minorities': minorities,
        }
        # Only reported when the source actually has the column: absent business
        # data must not be emitted as zeros. Added last rather than inline because
        # it is conditional; XML element order is unaffected, since
        # _build_demographics_section walks its own key_to_xml_map, not this dict.
        # (The 'race' sub-dict is the one whose order *is* load-bearing -- it is
        # iterated directly -- and it keeps DEMOGRAPHIC_KEYWORDS order.)
        if business_col:
            demographics['currently_in_business'] = currently_in_business
            demographics['not_in_business'] = not_in_business

        return demographics

    def _build_demographics_section(self, parent, demographics):
        number_trained = create_element(parent, 'NumberTrained')
        create_element(number_trained, 'Total', str(demographics.get('total', 0)))

        # Simple demographics
        key_to_xml_map = {
            'currently_in_business': 'CurrentlyInBusiness',
            'not_in_business': 'NotYetInBusiness',
            'disabilities': 'PersonWithDisabilities',
            'female': 'Female',
            'male': 'Male',
            'active_duty': 'ActiveDuty',
            'veterans': 'Veterans',
            'service_disabled_veterans': 'ServiceDisabledVeterans',
            'reserve_guard': 'MemberOfReserveOrNationalGuard',
            'military_spouse': 'SpouseOfMilitaryMember'
        }
        for key, xml_tag in key_to_xml_map.items():
            if demographics.get(key, 0) > 0:
                create_element(number_trained, xml_tag, str(demographics[key]))

        # Race
        if any(v > 0 for v in demographics.get('race', {}).values()):
            race_element = create_element(number_trained, 'Race')
            race_map = {'black': 'BlackOrAfricanAmerican', 'native_american': 'NativeAmericanOrAlaskaNative', 'pacific_islander': 'NativeHawaiianOrPacificIslander'}
            for key, count in demographics['race'].items():
                if count > 0:
                    xml_key = race_map.get(key, key.replace('_', ' ').title().replace(' ', ''))
                    create_element(race_element, xml_key, str(count))

        # Ethnicity
        if any(v > 0 for v in demographics.get('ethnicity', {}).values()):
            ethnicity_element = create_element(number_trained, 'Ethnicity')
            if demographics['ethnicity'].get('hispanic', 0) > 0:
                create_element(ethnicity_element, 'HispanicOrLatinoOrigin', str(demographics['ethnicity']['hispanic']))
            if demographics['ethnicity'].get('non_hispanic', 0) > 0:
                create_element(ethnicity_element, 'NonHispanicOrLatinoOrigin', str(demographics['ethnicity']['non_hispanic']))

        # Minorities
        if demographics.get('minorities', 0) > 0:
            minorities_element = create_element(parent, 'NumberUnderservedTrained')
            create_element(minorities_element, 'Total', str(demographics['minorities']))