"""
Handles the conversion of Salesforce counseling data (Form 641) from CSV to XML.
"""

import xml.etree.ElementTree as ET
import re

from .base_converter import BaseConverter, EmptyCSVError
from ..config import (
    BUSINESS_STARTUP_PREPLANNING,
    COUNSELING_FABRICATION_DEFAULTS,
    EXPORT_COUNTRY_LOOKUP,
    VALID_FUNDING_SOURCES,
    CounselingConfig,
    GeneralConfig,
    ValidationCategory,
)
from .. import data_cleaning
from .. import data_validation
from ..schema_rules import SchemaGuard
from ..xml_utils import create_element, emit_optional

def _session_type_key(value):
    return re.sub(r'[\s-]+', '', str(value).casefold())


_SESSION_TYPE_LOOKUP = {_session_type_key(t): t for t in CounselingConfig.VALID_SESSION_TYPES}


class CounselingConverter(BaseConverter):
    """
    Converter for Counseling (Form 641) data.
    """
    # Which schema's facets SchemaGuard enforces, and whose CSV column names
    # its issues use (training-client overrides this).
    SCHEMA_TYPE = "counseling"
    IDENTIFIER_COLUMNS = ('Contact ID', 'Activity ID')
    # The column PartnerSessionNumber is read from, which a blank session
    # number is reported against, and how that warning starts.
    SESSION_NUMBER_FIELD = 'Activity ID'
    SESSION_NUMBER_BLANK = "Blank Activity ID"

    def __init__(self, logger, validator):
        super().__init__(logger, validator)
        self.config = CounselingConfig()
        self.general_config = GeneralConfig()
        self._schema_guard = SchemaGuard(self.SCHEMA_TYPE, validator, logger)
        self._has_activity_column = True  # set per file by _check_session_column
        # The record being built's column-per-element overrides (see _mapped).
        self._record_columns = {}
        # Fabrication-risk fields (plan 1.3): when one of these is blank/missing
        # for a row and a non-empty default is emitted in its place, a
        # FABRICATED_DEFAULT warning is recorded. Subclasses narrow this set for
        # fields their own form intentionally defaults (see TrainingClientConverter).
        self.fabrication_warn_fields = set(COUNSELING_FABRICATION_DEFAULTS)
        self._fabrication_warned = set()
        # Per-row dedupe for warnings raised from code that runs more than once
        # per record (the address is built for Part 1 and Part 3), keyed by
        # (record_id, field). Cleared with _fabrication_warned at each row.
        self._warned_once = set()

    # Sections the XSD makes optional but this converter requires under a
    # condition: (ClientIntake child, CSV column, why it is required).
    _CONDITIONAL_SECTIONS = (
        ('CounselingSeeking', 'Nature of the Counseling Seeking?', 'for a client who is in business'),
        ('LegalEntity', 'Legal Entity of Business', 'for a client who is in business'),
        ('BranchOfService', 'Branch Of Service', 'for a client with military service'),
    )

    def _conditionally_required(self, record):
        """The conditionally required sections present before the schema
        guard runs, whose condition holds for this record."""
        intake = record.find('ClientIntake')
        if intake is None:
            return []
        in_business = intake.findtext('CurrentlyInBusiness') == 'Yes'
        military = (intake.findtext('MilitaryStatus') or '').lower() not in (
            '', 'no military service', 'prefer not to say')
        applies = {'CounselingSeeking': in_business, 'LegalEntity': in_business, 'BranchOfService': military}
        return [section for section in self._CONDITIONAL_SECTIONS
                if applies[section[0]] and intake.find(section[0]) is not None]

    def _report_conditional_drops(self, record, sections, record_id):
        """The guard may drop an optional section whose value SBA doesn't
        accept, with a warning -- right for the schema, but the converter's
        own "required when ..." check had already passed on the non-blank
        cell. Record the requirement the drop breaks as an error."""
        intake = record.find('ClientIntake')
        for tag, column, condition in sections:
            if intake is None or intake.find(tag) is None:
                self.validator.add_issue(
                    record_id, "error", ValidationCategory.MISSING_REQUIRED, column,
                    f"'{column}' is required {condition}, but its value is not one SBA accepts, "
                    "so it was left out of the XML.")

    def _warn_constant_defaults(self, headers):
        """Hook for converters that stamp configured values into every record
        (see TrainingClientConverter). Nothing to report for counseling, whose
        defaults are per-row FABRICATED_DEFAULT warnings."""

    def _preprocess_row(self, row):
        """Hook for subclasses to transform a row before processing. Returns the row unchanged by default."""
        return row

    def _mapped(self, row, mapping_key, element, default=''):
        """Read a column by its CounselingConfig.COLUMN_MAPPING key.

        Used for the Part 3 impact fields, whose fallback chain ("(Meeting)"
        column, else the intake column) is declared once in config instead of
        being repeated at each call site. Delegates to _first_present so the
        blank-vs-absent semantics below are the same either way.

        The column that supplied the value is recorded against `element`
        ("Parent/Tag"), so an issue about it names that column: a bad
        "(Meeting)" value used to be blamed on the intake column, whose cell
        could hold a perfectly good number.
        """
        for header in self.config.headers_for(mapping_key):
            value = self._first_present(row, header)
            if value:
                self._record_columns[element] = header
                return value
        return default

    def _column_for(self, element, mapping_key):
        """The CSV column _mapped() read `element` from in this row, else the
        first header `mapping_key` names."""
        return self._record_columns.get(element) or self.config.headers_for(mapping_key)[0]

    @staticmethod
    def _first_present(row, *keys, default=''):
        """First non-blank value among `keys`, else `default`.

        Written because `row.get(a, row.get(b, default))` does NOT express
        "a, falling back to b": the inner get is the *default argument*, so it
        is only consulted when column `a` is absent entirely. When `a` exists
        but the cell is blank, `''` wins and `b` is never read -- the opposite
        of the intended fallback, and exactly the case that arises when a
        Salesforce export includes a "(Meeting)" column that isn't filled in
        for every row.
        """
        for key in keys:
            value = row.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return default

    def _yes_no(self, row, column, default, record_id, *, undetermined=False):
        """Read a Yes/No (or Yes/No/Undetermined) column as the XSD spells it.

        These elements used to compare the cell against the literal 'Yes', so
        a client who answered "yes" to Currently In Business was filed as
        *not* in business, with nothing in the report. yes/y/true/1 and
        no/n/false/0 are accepted in any case (the same words is_affirmative
        and is_negative already use for OnFile and Employee_Owned), and a
        blank cell takes `default`. Anything else also takes `default`, but
        with a warning, so "Maybe" can't quietly become a federal "No".
        """
        raw = (row.get(column) or '').strip()
        if not raw:
            return default
        if data_cleaning.is_affirmative(raw):
            return 'Yes'
        if data_cleaning.is_negative(raw):
            return 'No'
        if undetermined and raw.casefold() == 'undetermined':
            return 'Undetermined'
        allowed = "Yes, No or Undetermined" if undetermined else "Yes or No"
        self.validator.add_issue(
            record_id, "warning", ValidationCategory.INVALID_VALUE, column,
            f"'{raw}' is not {allowed}; recorded as '{default}'.")
        return default

    def _optional_date(self, raw, column, record_id):
        """A date cell as YYYY-MM-DD for an optional element, or '' to leave
        the element out. A cell that holds something other than a date is
        reported rather than dropped without a word."""
        date = data_cleaning.format_date(raw)
        if not date and not data_cleaning.is_empty(raw):
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.INVALID_FORMAT, column,
                f"'{str(raw).strip()}' is not a date this tool can read, so it was left out of the XML.")
        return date

    def _optional_number(self, raw, column, record_id):
        """A numeric cell for an optional element, or '' to leave the element
        out. "10-20" or "1:30" is reported rather than dropped without a word."""
        number = data_cleaning.clean_numeric(raw)
        if not number and not data_cleaning.is_empty(raw):
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.INVALID_FORMAT, column,
                f"'{str(raw).strip()}' is not a number, so it was left out of the XML.")
        return number

    def _warn_not_filed(self, record_id, column, raw, why):
        """Report a filled cell the converter leaves out of the XML on purpose."""
        if not data_cleaning.is_empty(raw):
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.DOWNGRADED_VALUE, column,
                f"'{str(raw).strip()}' was left out of the XML because {why}.")

    def _warn_inferred_other(self, record_id, column, code, other_column):
        """Report a Code filed only because the matching "Other" text is filled:
        the schema needs a Code in the section, and the text is an "Other" answer."""
        self.validator.add_issue(
            record_id, "warning", ValidationCategory.DOWNGRADED_VALUE, column,
            f"'{column}' is blank, so it was filed as '{code}' because '{other_column}' is filled.")

    def _resolve_in_business(self, in_business_val, row, record_id):
        """Hook for subclasses to adjust the normalized in-business status before
        it is emitted and used to gate the in-business-only sections. Returns the
        value unchanged by default."""
        return in_business_val

    def _partner_session_number(self, row):
        """Hook for subclasses to choose the PartnerSessionNumber value.
        Defaults to the Activity ID."""
        return (row.get(CounselingConverter.SESSION_NUMBER_FIELD) or '').strip()

    def _check_session_column(self, headers):
        """Without an Activity ID column every session is filed with an empty
        PartnerSessionNumber. That validates, but leaves SBA nothing to tell
        the sessions apart by, so it is said once for the file rather than on
        every row (see _warn_blank_session_number)."""
        column = self.SESSION_NUMBER_FIELD
        self._has_activity_column = column in headers
        if not self._has_activity_column:
            self.validator.add_issue(
                "file", "warning", ValidationCategory.MISSING_FIELD, column,
                f"The CSV has no '{column}' column, so every session is filed with an empty "
                "session number (PartnerSessionNumber). Add the column if your export has it.",
                event_id="")

    def _warn_blank_session_number(self, record_id):
        if self._has_activity_column:
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.MISSING_FIELD, self.SESSION_NUMBER_FIELD,
                f"{self.SESSION_NUMBER_BLANK}, so this session is filed with an empty session "
                "number (PartnerSessionNumber).")

    def _first_time(self, record_id, field):
        """True the first time (record_id, field) is seen in the current row."""
        key = (record_id, field)
        if key in self._warned_once:
            return False
        self._warned_once.add(key)
        return True

    def _warn_fabricated_default(self, record_id, field, default_value, element_label, raw=None,
                                 always=False):
        """Record a FABRICATED_DEFAULT warning when a blank/missing cell is replaced
        by a non-empty default that ships in the XML. One warning per (record, field),
        however many XML elements the default lands in.

        `raw` is the cell as written, for the case where it was *not* blank but
        could not be used ("(1,500)", "n/a", a zero duration): the message then
        says so instead of claiming the cell was blank.

        `always` reports it even for a field outside fabrication_warn_fields,
        for a value no configuration sets (the 0.5 contact-hours fallback).
        """
        if field not in self.fabrication_warn_fields and not always:
            return
        key = (record_id, field)
        if key in self._fabrication_warned:
            return
        self._fabrication_warned.add(key)
        raw_text = str(raw).strip() if raw is not None else ''
        what = f"'{raw_text}' could not be used and was replaced" if raw_text else "Blank value defaulted"
        self.validator.add_issue(
            record_id, "warning", ValidationCategory.FABRICATED_DEFAULT, field,
            f"{what} with '{default_value}' ({element_label})." if raw_text
            else f"{what} to '{default_value}' ({element_label}).",
        )

    def convert(self, input_path: str, output_path: str):
        """
        Performs the data conversion from a CSV file to an XML file.
        """
        self.logger.info(f"Starting conversion of counseling data: {input_path}")

        # CONV-2: headers normalized so a stray/doubled space in a column name
        # can't silently break row.get() lookups downstream.
        _, rows = self._read_csv(input_path)

        if not rows:
            # CONV-6: a headers-only / empty CSV must fail, not silently produce
            # an empty <CounselingInformation/>.
            self.validator.add_issue("file", "error", ValidationCategory.MISSING_REQUIRED, "input_file", "CSV has headers but no data rows to convert.")
            raise EmptyCSVError("CSV has no data rows to convert.")

        self._warn_constant_defaults(set(rows[0]))
        self._check_session_column(set(rows[0]))

        root = ET.Element('CounselingInformation')
        # One entry per CounselingRecord, in document order: the CSV row it was
        # built from and the columns that fed it, so an XSD error can name the
        # row and column the user has to fix (xsd_error_mapping).
        self.record_sources = []
        self.left_out_reasons = []
        processed_records = 0
        skipped_records = 0
        total_rows = len(rows)

        # Emit an initial "0 of N" tick so the progress bar anchors at
        # zero rather than an empty state while the first row runs.
        self._report_progress(0, total_rows)

        for row_index, row in enumerate(rows, 1):
            if self._convert_row(root, row, row_index):
                processed_records += 1
            else:
                skipped_records += 1
            self._maybe_report_progress(row_index, total_rows)

        # Final tick so the bar ends at 100% regardless of batch size.
        self._report_progress(total_rows, total_rows)

        # File-level issues below must not inherit the last row's event id.
        self.validator.set_current_event_id(None)

        if processed_records == 0:
            # Every row was skipped: an empty <CounselingInformation/> fails the
            # XSD (it needs at least one CounselingRecord), so fail the way the
            # empty-CSV case above and the training converter already do
            # rather than writing a file SBA would reject.
            raise self._nothing_converted(f"{total_rows} row(s)")

        try:
            left_out = self._write_valid_xml(root, output_path)
            self.logger.info(f"XML file created successfully with {processed_records - left_out} "
                             f"records at {output_path}")
            if skipped_records + left_out > 0:
                self.logger.info(f"Skipped {skipped_records + left_out} records due to validation errors.")
        except OSError as e:
            self.logger.error(f"Failed to write XML file: {str(e)}")
            self.validator.add_issue("file", "error", ValidationCategory.FILE_WRITE, "output_file", f"Failed to write XML file: {str(e)}")
            raise

    def _convert_row(self, root, row, row_index) -> bool:
        """Append the CounselingRecord for one CSV row to `root`. Returns
        whether it was filed; a row that can't be is left out, with the
        reason recorded."""
        csv_row = row
        row = self._preprocess_row(row)
        cleaned_ids = self._clean_identifiers(row)
        contact_id = row.get('Contact ID')
        if contact_id is not None:
            # A whitespace-only id was written to the filing as "   ";
            # trimmed, it fails as a missing id like a blank cell does.
            row['Contact ID'] = contact_id = str(contact_id).strip()
        record_id = contact_id if contact_id is not None else f"Row_{row_index}"
        activity_id = row.get('Activity ID', '')
        # Set before validate_counseling_record so pre-validation issues
        # (including missing-Contact-ID "Row_N" ones) carry the event id.
        self.validator.set_current_event_id(activity_id)
        # Reset per row so duplicate Contact IDs still warn independently.
        self._fabrication_warned.clear()
        self._warned_once.clear()

        if not data_validation.validate_counseling_record(row, row_index, self.validator, csv_row):
            self.logger.warning(f"Skipping record {record_id} due to initial validation errors")
            self.left_out_reasons.append(f"row {row_index}: " + ("not a record" if contact_id else "no Contact ID"))
            # Counted, so "Total Records" is every row and the ones left out
            # are the difference from "Successful".
            self.validator.record_processed(success=False)
            return False
        self._report_cleaned_identifiers(cleaned_ids, record_id)

        counseling_record = create_element(root, 'CounselingRecord')
        self._record_columns = {}
        self.record_sources.append({"row": row_index, "event": activity_id,
                                    "columns": self._record_columns})
        try:
            filed = self._fill_record(root, counseling_record, row, record_id)
        except (ValueError, KeyError, AttributeError) as e:
            self.logger.error(f"Error processing record {record_id}: {str(e)}", exc_info=True)
            self.validator.add_issue(record_id, "error", ValidationCategory.PROCESSING_ERROR, "record", f"Error processing record: {str(e)}")
            # Half built, so never valid; the error above explains it.
            self._leave_out(root, counseling_record, f"{record_id}: an error while converting it ({e})")
            filed = False
        self.validator.record_processed(success=filed)
        return filed

    def _fill_record(self, root, counseling_record, row, record_id) -> bool:
        """Build the record's content. Returns False, having left the record
        out, when SchemaGuard finds a required value no fix can make valid."""
        create_element(counseling_record, 'PartnerClientNumber', record_id)

        location = create_element(counseling_record, 'Location')
        # `or`, not the .get default: a LocationCode column with a blank
        # cell must fall back too, or it emits <LocationCode/>, which the
        # xs:integer type rejects.
        create_element(location, 'LocationCode',
                       (row.get('LocationCode') or '').strip() or self.general_config.DEFAULT_LOCATION_CODE)

        self._build_client_request_section(counseling_record, row, record_id)
        self._build_client_intake_section(counseling_record, row, record_id)
        self._build_counselor_record_section(counseling_record, row, record_id)
        # Last, on the finished record: lengths, enumerations, patterns
        # and ranges straight from the XSD (see src/schema_rules.py).
        conditional = self._conditionally_required(counseling_record)
        unfileable = self._schema_guard.enforce(counseling_record, record_id, (root.tag,),
                                                self._record_columns)
        if unfileable:
            # A required value no fix can make valid -- a Contact ID over 20
            # characters, a LocationCode that isn't a number. The guard
            # recorded why; filing the record anyway would make SBA reject the
            # whole file, so it is left out.
            self._leave_out(root, counseling_record, f"{record_id}, {unfileable[0]}")
            return False
        self._report_conditional_drops(counseling_record, conditional, record_id)
        return True

    def _build_client_request_section(self, parent, row, record_id):
        client_request = create_element(parent, 'ClientRequest')
        client_name = create_element(client_request, 'ClientNamePart1')
        create_element(client_name, 'Last', row.get('Last Name', ''))
        create_element(client_name, 'First', row.get('First Name', ''))
        emit_optional(client_name, 'Middle', row.get('Middle Name', ''))
        # Email is minOccurs="0" but pattern-constrained (EmailType), so a blank
        # cell must omit the element rather than emit <Email/>.
        emit_optional(client_request, 'Email', row.get('Email', ''))
        self._build_phone(client_request, 'PhonePart1', row, record_id)
        self._build_address(client_request, 'AddressPart1', row, record_id)
        # SurveyAgreement is required and YesNoType, so it can't be omitted:
        # a blank cell falls back to 'No'.
        create_element(client_request, 'SurveyAgreement',
                       self._yes_no(row, 'Agree to Impact Survey', 'No', record_id))
        signature = create_element(client_request, 'ClientSignature')
        emit_optional(signature, 'Date', self._optional_date(
            row.get('Client Signature - Date', ''), 'Client Signature - Date', record_id))
        # _yes_no, not `in ['1', 1]`: a checkbox exported as "Yes"/"true"/"Y"
        # was silently recorded as "No" in a federal filing, and "Signed" still
        # was until it warned like the other Yes/No columns.
        create_element(signature, 'OnFile',
                       self._yes_no(row, 'Client Signature(On File)', 'No', record_id))

    @staticmethod
    def _classify_races(raw):
        """(codes, descriptions, unlisted) for a Race cell: each answer's SBA
        code, once and in order; the text to file as SelfDescribedRace; and
        those descriptions that weren't given as one, to warn about."""
        codes, descriptions, unlisted = [], [], []
        for label in data_cleaning.split_multi_value(raw):
            code, description = data_cleaning.classify_race_label(label)
            if code and code not in codes:
                codes.append(code)
            if description:
                descriptions.append(description)
                if not data_cleaning.is_self_describe_answer(label):
                    unlisted.append(description)
        return codes, descriptions, unlisted

    def _build_race(self, client_intake, row, record_id):
        race_element = create_element(client_intake, 'Race')
        codes, descriptions, unlisted = self._classify_races(row.get('Race', ''))
        if not codes:
            codes = [data_cleaning.RACE_PREFER_NOT_TO_SAY]
            self.validator.add_issue(record_id, "warning", ValidationCategory.MISSING_FIELD, "Race", "Race missing, defaulted to 'Prefer not to say'.")
        for code in codes:
            create_element(race_element, 'Code', code)
        if descriptions:
            # After every Code, as the schema orders them; at most 80
            # characters, which the schema guard enforces (and reports).
            create_element(race_element, 'SelfDescribedRace', '; '.join(descriptions))
        if unlisted:
            listed = ', '.join(f"'{d}'" for d in unlisted)
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.INVALID_VALUE, "Race",
                f"{listed} {'is' if len(unlisted) == 1 else 'are'} not among SBA's race "
                f"categories, so the answer was filed as '{data_cleaning.RACE_SELF_DESCRIBE}' "
                "with the text as written.")

    def _build_demographics(self, client_intake, row, record_id):
        # Each of these is an XSD enumeration, so the raw CSV label has to be
        # mapped before it is emitted -- Salesforce exports "Not Hispanic or
        # Latino", which is not a member of the schema's enum.
        self._emit_mapped_enum(client_intake, 'Ethnicity', row.get('Ethnicity:', ''),
                               data_cleaning.map_ethnicity_to_xsd, record_id, 'Ethnicity:')
        self._emit_mapped_enum(client_intake, 'Sex', row.get('Gender', ''),
                               data_cleaning.map_gender_to_sex, record_id, 'Gender')
        self._emit_mapped_enum(client_intake, 'Disability', row.get('Disability', ''),
                               data_cleaning.map_disability_to_xsd, record_id, 'Disability')

    def _emit_mapped_enum(self, parent, element_name, raw_value, mapper, record_id, column):
        """Emit an enumerated element via `mapper`, omitting it when unmappable.

        An unrecognized value is dropped rather than passed through: one
        enum-invalid element fails validation for the entire document, and every
        element using this path is minOccurs="0". It is reported, so the
        answer doesn't vanish without a word.
        """
        mapped = mapper(raw_value)
        emit_optional(parent, element_name, mapped)
        if not mapped and not data_cleaning.is_empty(raw_value):
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.INVALID_VALUE, column,
                f"'{str(raw_value).strip()}' is not one of the answers SBA accepts for "
                f"{element_name}, so it was left out of the XML.")
        return mapped

    def _build_military_status(self, client_intake, row, record_id):
        military_status_raw = row.get('Veteran Status', '').strip()
        military_status_csv = data_cleaning.map_military_status_to_xsd(military_status_raw)
        if military_status_raw and not military_status_csv:
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.INVALID_VALUE, "Veteran Status",
                f"Veteran Status '{military_status_raw}' is not a recognized military "
                f"status and was omitted from the XML.",
            )
        emit_optional(client_intake, 'MilitaryStatus', military_status_csv)

        non_military_statuses = ['prefer not to say', 'no military service', '']
        branch_csv = row.get('Branch Of Service', '').strip()
        if military_status_csv and military_status_csv.lower() not in non_military_statuses:
            # 'Prefer not to say' is one of SBA's branches, so only a blank
            # cell or "no military service" means no branch was given.
            if branch_csv and branch_csv.lower() != 'no military service':
                create_element(client_intake, 'BranchOfService',
                               data_cleaning.map_branch_of_service_to_xsd(branch_csv))
            else:
                self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED, "BranchOfService", f"BranchOfService required for MilitaryStatus '{military_status_csv}' but is missing/invalid.")
        else:
            self._warn_not_filed(
                record_id, 'Branch Of Service', branch_csv,
                f"Veteran Status is '{military_status_raw or 'blank'}', not military service")

    def _build_media_and_internet(self, client_intake, row, record_id):
        media_codes = data_cleaning.split_multi_value(row.get('What Prompted you to contact us?', ''))
        if media_codes:
            media = create_element(client_intake, 'Media')
            for code in media_codes:
                create_element(media, 'Code', code)

        # "Internet (specify)" names the internet source behind a media answer
        # of "Internet", which the schema files in its own Internet element.
        # It used to go to Media/Other -- SBA's text for a media answer of
        # "Other" -- and with no media answer given that left a Media section
        # with no Code, which fails the schema. InternetUsage, the older
        # column, is the fallback.
        internet = self._mapped(row, 'internet', 'ClientIntake/Internet')
        if internet:
            create_element(client_intake, 'Internet', internet)

        has_internet_media = any(c.strip().lower() == 'internet' for c in media_codes)
        if has_internet_media and not internet:
            self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED,
                "Internet", "Internet field should be mandatory when the media code is 'Internet'.")

    def _build_business_fields(self, client_intake, row, record_id):
        """Build business status, ownership, employees, and income fields. Returns in_business_val."""
        in_business_val = self._yes_no(row, 'Currently In Business?', self.general_config.DEFAULT_BUSINESS_STATUS,
                                       record_id, undetermined=True)
        in_business_val = self._resolve_in_business(in_business_val, row, record_id)
        create_element(client_intake, 'CurrentlyInBusiness', in_business_val)

        exporting_val = self._yes_no(row, 'Are you currently exporting?(old)',
                                     self.general_config.DEFAULT_BUSINESS_STATUS, record_id)
        if data_cleaning.is_empty(row.get('Are you currently exporting?(old)')):
            self._warn_fabricated_default(record_id, 'Are you currently exporting?(old)', exporting_val,
                                          'Currently Exporting')
        # Part 3 repeats this answer; it used to hardcode 'No' there, so an
        # exporting client was filed as exporting and not exporting at once.
        self._currently_exporting = exporting_val
        create_element(client_intake, 'CurrentlyExporting', exporting_val)

        create_element(client_intake, 'CompanyName', row.get('Account Name', ''))
        business_type = row.get('Type of Business', '').strip()
        if business_type:
            create_element(client_intake, 'BusinessType', business_type)

        bo_element = create_element(client_intake, 'BusinessOwnership')
        female_raw = row.get('Business Ownership - % Female(old)', '0')
        female_ownership_val = data_cleaning.clean_percentage(female_raw)
        if data_cleaning.is_empty(row.get('Business Ownership - % Female(old)')):
            self._warn_fabricated_default(record_id, 'Business Ownership - % Female(old)', female_ownership_val, '% Female Ownership')
        elif not data_cleaning.is_percentage(female_raw):
            self._warn_fabricated_default(record_id, 'Business Ownership - % Female(old)', female_ownership_val,
                                          '% Female Ownership', raw=female_raw)
        if data_cleaning.percentage_was_clamped(female_raw):
            # CONV-7: record the out-of-range original before clean_percentage clamps it.
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.CLAMPED_VALUE,
                "BusinessOwnership/Female",
                f"% Female ownership '{str(female_raw).strip()}' is outside 0-100 "
                f"and was clamped to {female_ownership_val}.",
            )
        create_element(bo_element, 'Female', female_ownership_val)

        # Both of these are YesNoType (strictly Yes/No), so a blank cell falls
        # back to the default -- and says so.
        conducting_online = self._yes_no(row, 'Conduct Business Online?',
                                         self.general_config.DEFAULT_BUSINESS_STATUS, record_id)
        if data_cleaning.is_empty(row.get('Conduct Business Online?')) and conducting_online:
            self._warn_fabricated_default(record_id, 'Conduct Business Online?', conducting_online, 'Conducting Business Online')
        create_element(client_intake, 'ConductingBusinessOnline', conducting_online)
        certified_8a = self._yes_no(row, '8(a) Certified?(old)',
                                    self.general_config.DEFAULT_BUSINESS_STATUS, record_id)
        if data_cleaning.is_empty(row.get('8(a) Certified?(old)')) and certified_8a:
            self._warn_fabricated_default(record_id, '8(a) Certified?(old)', certified_8a, '8(a) Certified')
        create_element(client_intake, 'ClientIntake_Certified8a', certified_8a)
        # Employee_Owned is optional (minOccurs=0): emit only when the CSV provides
        # an affirmative/negative value; omit entirely when absent/blank or
        # unrecognized (never fabricated).
        employee_owned_raw = row.get('Employee Owned', '')
        if data_cleaning.is_affirmative(employee_owned_raw):
            create_element(client_intake, 'Employee_Owned', 'Yes')
        elif data_cleaning.is_negative(employee_owned_raw):
            create_element(client_intake, 'Employee_Owned', 'No')
        else:
            self._warn_not_filed(record_id, 'Employee Owned', employee_owned_raw, "it is not Yes or No")
        total_emp_intake = self._optional_number(row.get('Total Number of Employees', ''),
                                                 'Total Number of Employees', record_id)
        if total_emp_intake:
            create_element(client_intake, 'TotalNumberOfEmployees', total_emp_intake)
        # Read once for Part 2 and Part 3; the schema guard reports a negative.
        self._exporting_employees = self._optional_number(
            row.get('Number of Employees in Exporting Business', ''),
            'Number of Employees in Exporting Business', record_id)
        exporting_employees1 = self._exporting_employees
        if exporting_employees1:
            # Not int(): 12.7 became 12 with no issue. Part 2 is an xs:decimal;
            # for Part 3's whole number the schema guard rewrites 12.0 as 12
            # and reports a fraction.
            create_element(client_intake, 'NumberOfEmployeesInExportingBusiness', exporting_employees1)

        income_part2 = create_element(client_intake, 'ClientAnnualIncomePart2')
        gross_rev = data_cleaning.clean_numeric(row.get('Gross Revenues/Sales', ''))
        if not gross_rev:
            self._warn_fabricated_default(record_id, 'Gross Revenues/Sales', '0', 'Gross Revenues',
                                          raw=row.get('Gross Revenues/Sales'))
        create_element(income_part2, 'GrossRevenues', gross_rev if gross_rev else '0')
        profit_loss = data_cleaning.clean_numeric(row.get('Profits/Losses', ''))
        if not profit_loss:
            self._warn_fabricated_default(record_id, 'Profits/Losses', '0', 'Profit/Loss',
                                          raw=row.get('Profits/Losses'))
        create_element(income_part2, 'ProfitLoss', profit_loss if profit_loss else '0')
        self._emit_export_revenue(income_part2)

        return in_business_val

    def _emit_export_revenue(self, income_element):
        """ExportGrossRevenuesOrSales has no CSV column. Zero follows from the
        client's "not exporting" answer; for an exporter the figure is simply
        unknown, so it is omitted (the element is optional) rather than filed
        as a fabricated 0."""
        if self._currently_exporting == 'No':
            create_element(income_element, 'ExportGrossRevenuesOrSales', '0')

    def _build_legal_entity(self, client_intake, row, record_id):
        le_element = create_element(client_intake, 'LegalEntity')
        le_codes = data_cleaning.split_multi_value(row.get('Legal Entity of Business', ''))
        le_other = row.get('Other legal entity (specify)', '').strip()
        if le_codes:
            for code in le_codes:
                create_element(le_element, 'Code', code)
        elif le_other:
            create_element(le_element, 'Code', 'Other')
            self._warn_inferred_other(record_id, 'Legal Entity of Business', 'Other',
                                      'Other legal entity (specify)')
        else:
            self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED, "LegalEntity", "Client is in business, but Legal Entity is missing.")
            create_element(le_element, 'Code', 'Other')
        if le_other:
            create_element(le_element, 'Other', le_other)

    def _build_rural_urban(self, client_intake, row, record_id):
        rural_urban_val = (row.get('Rural_vs_Urban') or '').strip() or self.config.DEFAULT_URBAN_RURAL
        create_element(client_intake, 'Rural_vs_Urban', rural_urban_val)

        fips_code = row.get('FIPS_Code', '').strip()
        if rural_urban_val.lower() in ['rural', 'urban']:
            if fips_code:
                create_element(client_intake, 'FIPS_Code', fips_code)
            else:
                self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED, "FIPS_Code", f"FIPS Code required for Rural/Urban status '{rural_urban_val}' but is missing.")
        else:
            self._warn_not_filed(record_id, 'FIPS_Code', fips_code,
                                 f"Rural_vs_Urban is '{rural_urban_val}', not Rural or Urban")

    def _cap_single_code(self, codes, record_id, element_label, csv_field):
        """Trim a multi-value code list to the one Code the XSD allows.

        Salesforce joins multi-selects with ';' and split_multi_value expands
        them, but CounselingSeeking/Code and CounselingProvided/Code are both
        maxOccurs="1" -- emitting two makes the *whole document* invalid. Keep
        the first and record the dropped values so the loss stays auditable
        rather than silent.
        """
        if len(codes) <= 1:
            return codes
        dropped = codes[1:]
        self.validator.add_issue(
            record_id, "warning", ValidationCategory.DOWNGRADED_VALUE, csv_field,
            f"{element_label} accepts only one code; kept '{codes[0]}' and dropped "
            f"{', '.join(repr(c) for c in dropped)}.",
        )
        return codes[:1]

    def _build_counseling_seeking(self, client_intake, row, record_id, in_business_val):
        cs_codes = data_cleaning.split_multi_value(row.get('Nature of the Counseling Seeking?', ''))
        cs_other = row.get('Nature of the Counseling Seeking - Other Detail', '').strip()
        if cs_other and not cs_codes:
            # The detail is the text of an "Other" answer. Written on its own
            # it left CounselingSeeking with no Code, which the schema requires.
            cs_codes = ['Other']
            self._warn_inferred_other(record_id, 'Nature of the Counseling Seeking?', 'Other',
                                      'Nature of the Counseling Seeking - Other Detail')
        if cs_codes:
            cs_element = create_element(client_intake, 'CounselingSeeking')
            cs_codes = self._cap_single_code(cs_codes, record_id, 'CounselingSeeking',
                                             'Nature of the Counseling Seeking?')
            # Checked after capping: if 'Other' was dropped, its detail text is
            # no longer required.
            is_other_present = any(c.lower() == 'other' for c in cs_codes)
            for code in cs_codes:
                create_element(cs_element, 'Code', code)
            if is_other_present and not cs_other:
                self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED, "CounselingSeeking/Other", "CounselingSeeking is 'Other' but detail text is missing.")
            emit_optional(cs_element, 'Other', cs_other)

        if in_business_val == 'Yes' and not cs_codes:
            self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED,
                "CounselingSeeking", "Counseling Seeking is required under Part 2 if Client is in Business.")

    def _build_export_countries(self, client_intake, row, record_id):
        """Emit ExportCountries (last element of ClientIntake per the XSD sequence)
        when the CSV provides countries; omitted entirely when absent/blank (never
        fabricated). The XSD restricts Code to an enumeration of full country
        names, so each value is run through the same country standardization as
        addresses and then resolved case-insensitively against that enumeration.
        Values that don't resolve are omitted (with a warning) rather than
        emitted, since one enum-invalid Code fails validation for the whole
        document; if none resolve, the element is omitted entirely."""
        countries = data_cleaning.split_multi_value(row.get('Export Countries', ''))
        if not countries:
            return
        codes = []
        for country in countries:
            standardized = data_cleaning.standardize_country_code(country)
            canonical = EXPORT_COUNTRY_LOOKUP.get(standardized.lower())
            if canonical:
                codes.append(canonical)
            else:
                self.validator.add_issue(record_id, "warning", ValidationCategory.INVALID_VALUE, "Export Countries",
                    f"Export country '{country}' is not in the SBA country list and was omitted from the XML.")
        if not codes:
            return
        ec_element = create_element(client_intake, 'ExportCountries')
        for code in codes:
            create_element(ec_element, 'Code', code)

    def _build_client_intake_section(self, parent, row, record_id):
        client_intake = create_element(parent, 'ClientIntake')
        self._build_race(client_intake, row, record_id)
        self._build_demographics(client_intake, row, record_id)
        self._build_military_status(client_intake, row, record_id)
        self._build_media_and_internet(client_intake, row, record_id)
        in_business_val = self._build_business_fields(client_intake, row, record_id)
        if in_business_val.lower() == 'yes':
            self._build_legal_entity(client_intake, row, record_id)
        else:
            why = f"Currently In Business is '{in_business_val}', and SBA asks for it only of a business"
            self._warn_not_filed(record_id, 'Legal Entity of Business', row.get('Legal Entity of Business', ''), why)
            self._warn_not_filed(record_id, 'Other legal entity (specify)',
                                 row.get('Other legal entity (specify)', ''), why)
        self._build_rural_urban(client_intake, row, record_id)
        self._build_counseling_seeking(client_intake, row, record_id, in_business_val)
        self._build_export_countries(client_intake, row, record_id)

    def _build_counselor_identity(self, counselor_record, row, record_id):
        session_number = self._partner_session_number(row)
        if not session_number:
            self._warn_blank_session_number(record_id)
        create_element(counselor_record, 'PartnerSessionNumber', session_number)

        # FundingSource is an XSD enumeration of SBA disaster/program codes. A
        # partner's own funding label ("Federal", "CORE") is not in it, so an
        # unrecognized value must be omitted rather than emitted verbatim.
        funding_source = row.get('Funding Source', '').strip()
        if funding_source:
            emit_optional(counselor_record, 'FundingSource',
                          self._resolve_funding_source(funding_source, record_id))

        counselor_name_part3 = create_element(counselor_record, 'ClientNamePart3')
        create_element(counselor_name_part3, 'Last', row.get('Last Name', ''))
        create_element(counselor_name_part3, 'First', row.get('First Name', ''))
        emit_optional(counselor_name_part3, 'Middle', row.get('Middle Name', ''))

        emit_optional(counselor_record, 'Email', row.get('Email', ''))
        self._build_phone(counselor_record, 'PhonePart3', row, record_id)
        self._build_address(counselor_record, 'AddressPart3', row, record_id)

    def _resolve_funding_source(self, funding_source, record_id):
        """Return the funding source iff it matches the XSD enumeration, else ''."""
        cleaned = str(funding_source).strip()
        for valid_source in VALID_FUNDING_SOURCES:
            if valid_source.lower() == cleaned.lower():
                return valid_source
        self.validator.add_issue(
            record_id, "warning", ValidationCategory.INVALID_VALUE, "Funding Source",
            f"Funding Source '{cleaned}' is not a recognized SBA funding code; omitted from the XML.",
        )
        return ""

    def _build_business_verification(self, counselor_record, row, record_id):
        """Build business verification and reportable impact fields. Returns session-relevant values."""
        verified_in_business = self._yes_no(row, 'Verified To Be In Business', 'Undetermined',
                                            record_id, undetermined=True)
        reportable_impact = self._yes_no(row, 'Reportable Impact', self.general_config.DEFAULT_BUSINESS_STATUS,
                                         record_id)

        if reportable_impact == 'Yes' and verified_in_business != 'Yes':
            # A reportable impact presupposes a verified business, so the answer
            # is overridden -- but never silently.
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.DOWNGRADED_VALUE, 'Verified To Be In Business',
                f"Recorded as 'Yes' instead of '{verified_in_business}' because Reportable Impact is 'Yes'.")
            verified_in_business = 'Yes'

        create_element(counselor_record, 'VerifiedToBeInBusiness', verified_in_business)
        create_element(counselor_record, 'ReportableImpact', reportable_impact)

        impact_date = self._optional_date(row.get('Reportable Impact Date', ''), 'Reportable Impact Date', record_id)
        if impact_date:
            create_element(counselor_record, 'DateOfReportableImpact', impact_date)
        create_element(counselor_record, 'CurrentlyExporting', self._currently_exporting)

        business_start_raw = self._mapped(row, 'business_start_date', 'CounselorRecord/BusinessStartDatePart3')
        business_start_date = self._optional_date(
            business_start_raw, self._column_for('CounselorRecord/BusinessStartDatePart3', 'business_start_date'),
            record_id)
        if business_start_date:
            create_element(counselor_record, 'BusinessStartDatePart3', business_start_date)

    def _build_financial_data(self, counselor_record, row, record_id):
        # Omitted when blank, as Part 2 does: a default of '0' made a blank cell
        # indistinguishable from "no employees" in the filing.
        total_employees_raw = self._mapped(row, 'total_employees_part3', 'CounselorRecord/TotalNumberOfEmployees')
        total_employees = data_cleaning.clean_numeric(total_employees_raw)
        if total_employees:
            create_element(counselor_record, 'TotalNumberOfEmployees', total_employees)
        else:
            column = self._column_for('CounselorRecord/TotalNumberOfEmployees', 'total_employees_part3')
            if column != 'Total Number of Employees':  # Part 2 reported the intake column
                self._optional_number(total_employees_raw, column, record_id)

        exporting_employees2 = self._exporting_employees
        if exporting_employees2:
            create_element(counselor_record, 'NumberOfEmployeesInExportingBusiness', exporting_employees2)

        gross_rev_part3 = data_cleaning.clean_numeric(self._mapped(row, 'gross_revenues_part3', 'ClientAnnualIncomePart3/GrossRevenues'))
        profit_loss_part3 = data_cleaning.clean_numeric(self._mapped(row, 'profit_loss_part3', 'ClientAnnualIncomePart3/ProfitLoss'))
        income_part3 = create_element(counselor_record, 'ClientAnnualIncomePart3')
        # No fabrication warnings here for gross revenue / profit-loss: they are
        # keyed on the base columns (the "(Meeting)" variants are intentionally
        # excluded, see COUNSELING_FABRICATION_DEFAULTS) and Part 2 already warns
        # whenever the base column is blank, so warning again would be noise.
        create_element(income_part3, 'GrossRevenues', gross_rev_part3 if gross_rev_part3 else '0')
        create_element(income_part3, 'ProfitLoss', profit_loss_part3 if profit_loss_part3 else '0')
        self._emit_export_revenue(income_part3)

        # Default to '' (not '0') so an absent column is indistinguishable from a
        # blank cell here and both trip the fabrication warning; the emitted value
        # is unchanged because the create_element calls below fall back to '0'.
        sba_loan = data_cleaning.clean_numeric(row.get('SBA Loan Amount', ''))
        non_sba_loan = data_cleaning.clean_numeric(row.get('Non-SBA Loan Amount', ''))
        equity_capital = data_cleaning.clean_numeric(row.get('Amount of Equity Capital Received', ''))
        rpsc = create_element(counselor_record, 'ResourcePartnerServiceContributed')
        if not sba_loan:
            self._warn_fabricated_default(record_id, 'SBA Loan Amount', '0', 'SBA Loan Amount',
                                          raw=row.get('SBA Loan Amount'))
        create_element(rpsc, 'SBALoanAmount', sba_loan if sba_loan else '0')
        if not non_sba_loan:
            self._warn_fabricated_default(record_id, 'Non-SBA Loan Amount', '0', 'Non-SBA Loan Amount',
                                          raw=row.get('Non-SBA Loan Amount'))
        create_element(rpsc, 'NonSBALoanAmount', non_sba_loan if non_sba_loan else '0')
        if not equity_capital:
            self._warn_fabricated_default(record_id, 'Amount of Equity Capital Received', '0', 'Equity Capital Received',
                                          raw=row.get('Amount of Equity Capital Received'))
        create_element(rpsc, 'EquityCapitalReceived', equity_capital if equity_capital else '0')

    def _build_coded_section(self, parent, element_name, codes, other_text, default_other_code=None,
                             record_id=None, columns=None):
        """Build an optional section with Code elements and an Other field.
        `columns` names the (code, other text) CSV columns, for the warning
        when only the text is given and `default_other_code` is filed for it."""
        if not codes and not other_text:
            return
        element = create_element(parent, element_name)
        for code in codes:
            create_element(element, 'Code', code)
        if not codes and other_text and default_other_code:
            create_element(element, 'Code', default_other_code)
            if columns:
                self._warn_inferred_other(record_id, columns[0], default_other_code, columns[1])
        if other_text:
            create_element(element, 'Other', other_text)

    def _build_counseling_provided(self, counselor_record, row, record_id):
        cp_element = create_element(counselor_record, 'CounselingProvided')
        # CounselingProvided requires at least one Code, so a cell that gives
        # none falls back -- blank, or only separators (";"), which split to
        # nothing and used to leave the section without a Code.
        raw_provided = row.get('Services Provided')
        provided_codes = data_cleaning.split_multi_value(raw_provided or '')
        if not provided_codes:
            provided_codes = [BUSINESS_STARTUP_PREPLANNING]
            self._warn_fabricated_default(record_id, 'Services Provided', BUSINESS_STARTUP_PREPLANNING,
                                          'Counseling Provided',
                                          raw=None if data_cleaning.is_empty(raw_provided) else raw_provided)
        provided_codes = self._cap_single_code(provided_codes, record_id, 'CounselingProvided',
                                               'Services Provided')
        # 'Other' is a valid CounselingProvided code and is emitted as-is. It
        # used to be rewritten to 'Business Operations/Management', filing a
        # service the counselor never said they provided.
        has_other_code = any(c.strip().lower() == 'other' for c in provided_codes)
        cp_other = row.get('Other Counseling Provided', '').strip()
        for code in provided_codes:
            create_element(cp_element, 'Code', code)
        if has_other_code and not cp_other:
            self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED,
                "CounselingProvided/Other", "Other Counseling Provided is required when Counseling Provided Code is 'Other'.")
        if cp_other:
            create_element(cp_element, 'Other', cp_other)

    def _build_session_details(self, counselor_record, row, record_id):
        session_type_raw = row.get('Type of Session', self.config.DEFAULT_SESSION_TYPE)
        session_type = "Update Only" if session_type_raw.strip() == "Update" else session_type_raw.strip()
        # Ignoring case, spaces and hyphens: Salesforce's "Face to Face" is the
        # schema's "Face-to-face", and used to be filed as the default type.
        session_type = _SESSION_TYPE_LOOKUP.get(_session_type_key(session_type), session_type)
        if session_type not in self.config.VALID_SESSION_TYPES:
            self.validator.add_issue(record_id, "warning", ValidationCategory.INVALID_VALUE, "Type of Session",
                                     f"Invalid session type '{session_type_raw}', recorded as "
                                     f"'{self.config.DEFAULT_SESSION_TYPE}'.")
            session_type = self.config.DEFAULT_SESSION_TYPE
        create_element(counselor_record, 'SessionType', session_type)

        # Language requires at least one Code child, so a cell that gives none
        # (blank, or only separators) falls back to the default language rather
        # than producing a Language with no Code.
        lang_codes = (data_cleaning.split_multi_value(row.get('Language(s) Used') or '')
                      or [self.general_config.DEFAULT_LANGUAGE])
        lang_element = create_element(counselor_record, 'Language')
        for code in lang_codes:
            create_element(lang_element, 'Code', code)
        emit_optional(lang_element, 'Other', row.get('Language(s) Used (Other)', '').strip())

        date_raw = row.get('Date', '')
        date_counseled = data_cleaning.format_date(date_raw)
        if date_counseled:
            create_element(counselor_record, 'DateCounseled', date_counseled)
        if data_cleaning.is_ambiguous_date(date_raw):
            # CONV-3: emitted month-first, but flag the ambiguity for human review.
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.AMBIGUOUS_DATE,
                "DateCounseled",
                f"Date '{str(date_raw).strip()}' is ambiguous between MM/DD and "
                f"DD/MM; interpreted month-first as {date_counseled}.",
            )

        counselor_name = row.get('Name of Counselor', '').strip()
        if counselor_name:
            create_element(counselor_record, 'CounselorName', counselor_name)

        ch_element = create_element(counselor_record, 'CounselingHours')
        # All three are minOccurs="0" over xs:decimal, so an unparseable or blank
        # value must omit the element -- <Contact/> is not a valid decimal.
        contact_val = data_cleaning.clean_numeric((row.get('Duration (hours)') or '0'))
        if session_type not in self.config.NO_CONTACT_HOUR_SESSION_TYPES and float(contact_val or 0) <= 0:
            contact_val = "0.5"
            raw_duration = row.get('Duration (hours)')
            self._warn_fabricated_default(
                record_id, 'Duration (hours)', contact_val, f'Contact hours for a {session_type} session',
                raw=None if data_cleaning.is_empty(raw_duration) else raw_duration, always=True)
        emit_optional(ch_element, 'Contact', contact_val)
        emit_optional(ch_element, 'Prepare', self._optional_number(row.get('Prep Hours') or '0', 'Prep Hours', record_id))
        emit_optional(ch_element, 'Travel', self._optional_number(row.get('Travel Hours') or '0', 'Travel Hours', record_id))

        notes_limit = self.config.MAX_FIELD_LENGTHS["CounselorNotes"]
        counselor_notes = data_cleaning.truncate_counselor_notes(row.get('Comments', ''), notes_limit)
        full_length = len(data_cleaning.clean_whitespace(row.get('Comments', '')))
        if len(counselor_notes) < full_length:
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.TRUNCATED_VALUE, 'Comments',
                f"Counselor notes are {full_length} characters; SBA allows {notes_limit}, so "
                f"{full_length - len(counselor_notes)} characters at the end were cut.")
        if counselor_notes:
            create_element(counselor_record, 'CounselorNotes', counselor_notes)

    def _build_counselor_record_section(self, parent, row, record_id):
        counselor_record = create_element(parent, 'CounselorRecord')
        self._build_counselor_identity(counselor_record, row, record_id)
        self._build_business_verification(counselor_record, row, record_id)
        self._build_financial_data(counselor_record, row, record_id)

        self._build_coded_section(counselor_record, 'Certifications',
            data_cleaning.split_multi_value(row.get('Certifications (SDB, HUBZONE, etc)', '')),
            row.get('Other Certifications', '').strip(), 'Other',
            record_id, ('Certifications (SDB, HUBZONE, etc)', 'Other Certifications'))

        self._build_coded_section(counselor_record, 'SBAFinancialAssistance',
            data_cleaning.split_multi_value(row.get('SBA Financial Assistance', '')),
            row.get('Other SBA Financial Assistance', '').strip(), 'Other(SBIR, SBIC, 7(a) 504, etc)',
            record_id, ('SBA Financial Assistance', 'Other SBA Financial Assistance'))

        self._build_counseling_provided(counselor_record, row, record_id)

        self._build_coded_section(counselor_record, 'ReferredClient',
            data_cleaning.split_multi_value(row.get('Referred Client to', '')),
            row.get('Other (Referred Client to)', '').strip(), 'Other',
            record_id, ('Referred Client to', 'Other (Referred Client to)'))

        self._build_session_details(counselor_record, row, record_id)
        # Unused here; lets subclasses append trailing elements (e.g. TrainingSession).
        return counselor_record


    def _build_address(self, parent, element_name, row, record_id):
        address = create_element(parent, element_name)
        # Every child here is minOccurs="0", and State/ZipCode carry an
        # enumeration and a \d{5} pattern respectively -- so a blank cell must
        # omit the element, not emit an empty one (which fails validation).
        emit_optional(address, 'Street1', row.get('Mailing Street', ''))
        emit_optional(address, 'City', row.get('Mailing City', ''))
        emit_optional(address, 'State', data_cleaning.standardize_state_name(row.get('Mailing State/Province', '')))
        zip_full = str(row.get('Mailing Zip/Postal Code', '')).strip()
        # ZIP+4 written 50309-1234, 50309 1234 or 503091234: the last form
        # (how a spreadsheet stores it as a number) used to lose the +4.
        zip_match = re.match(r'^(\d{5})(?:[-\s]?(\d{4}))?', zip_full)
        zip_5digit = zip_match.group(1) if zip_match else ''
        unread = zip_full[zip_match.end():].strip() if zip_match else ''
        if zip_full and (not zip_5digit or unread) and self._first_time(record_id, 'Mailing Zip/Postal Code'):
            # Once per record, not once per address part: the same cell is read
            # for AddressPart1 and AddressPart3, and the report listed it twice.
            message = (f"Could not parse 5-digit ZIP from '{zip_full}'." if not zip_5digit
                       else f"Only '{zip_full[:zip_match.end()]}' of '{zip_full}' is a ZIP or ZIP+4, "
                            "so the rest was left out of the XML.")
            self.validator.add_issue(record_id, "warning", ValidationCategory.INVALID_FORMAT,
                                     "Mailing Zip/Postal Code", message)
        emit_optional(address, 'ZipCode', zip_5digit)
        # Zip4Code requires exactly 4 digits per XSD - only emit if we have it
        if zip_match and zip_match.group(2):
            create_element(address, 'Zip4Code', zip_match.group(2))
        country = create_element(address, 'Country')
        country_val = data_cleaning.standardize_country_code(row.get('Mailing Country', 'US'))
        if data_cleaning.is_empty(row.get('Mailing Country')):
            # Deduped per (record, field): the address is built for both
            # AddressPart1 and AddressPart3 but only one warning is recorded.
            self._warn_fabricated_default(record_id, 'Mailing Country', country_val, 'Mailing Country')
        create_element(country, 'Code', country_val)

    def _phone(self, row, column, record_id):
        """The cell as ten digits, or '' -- reported when a number was given
        but couldn't be read (PhoneType is exactly ten digits). Once per
        record, though the phone is built for Part 1 and Part 3."""
        raw = row.get(column, '')
        phone = data_cleaning.clean_phone_number(raw)
        if not phone and not data_cleaning.is_empty(raw) and self._first_time(record_id, column):
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.INVALID_FORMAT, column,
                f"'{str(raw).strip()}' is not a 10-digit phone number, so it was left out of the XML.")
        return phone

    def _build_phone(self, parent, element_name, row, record_id):
        primary_phone = self._phone(row, 'Contact: Phone', record_id)
        secondary_phone = self._phone(row, 'Contact: Secondary Phone', record_id)
        # Only emit phone element if at least one number is present
        if primary_phone or secondary_phone:
            phone = create_element(parent, element_name)
            if primary_phone:
                create_element(phone, 'Primary', primary_phone)
            if secondary_phone:
                create_element(phone, 'Secondary', secondary_phone)
