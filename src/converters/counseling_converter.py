"""
Handles the conversion of Salesforce counseling data (Form 641) from CSV to XML.
"""

import csv
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
from ..xml_utils import create_element, emit_optional

class CounselingConverter(BaseConverter):
    """
    Converter for Counseling (Form 641) data.
    """
    def __init__(self, logger, validator):
        super().__init__(logger, validator)
        self.config = CounselingConfig()
        self.general_config = GeneralConfig()
        # Fabrication-risk fields (plan 1.3): when one of these is blank/missing
        # for a row and a non-empty default is emitted in its place, a
        # FABRICATED_DEFAULT warning is recorded. Subclasses narrow this set for
        # fields their own form intentionally defaults (see TrainingClientConverter).
        self.fabrication_warn_fields = set(COUNSELING_FABRICATION_DEFAULTS)
        self._fabrication_warned = set()

    def _preprocess_row(self, row):
        """Hook for subclasses to transform a row before processing. Returns the row unchanged by default."""
        return row

    def _resolve_in_business(self, in_business_val, row, record_id):
        """Hook for subclasses to adjust the normalized in-business status before
        it is emitted and used to gate the in-business-only sections. Returns the
        value unchanged by default."""
        return in_business_val

    def _partner_session_number(self, row):
        """Hook for subclasses to choose the PartnerSessionNumber value.
        Defaults to the Activity ID."""
        return row.get('Activity ID', '')

    def _warn_fabricated_default(self, record_id, field, default_value, element_label):
        """Record a FABRICATED_DEFAULT warning when a blank/missing cell is replaced
        by a non-empty default that ships in the XML. One warning per (record, field),
        however many XML elements the default lands in."""
        if field not in self.fabrication_warn_fields:
            return
        key = (record_id, field)
        if key in self._fabrication_warned:
            return
        self._fabrication_warned.add(key)
        self.validator.add_issue(
            record_id, "warning", ValidationCategory.FABRICATED_DEFAULT, field,
            f"Blank value defaulted to '{default_value}' ({element_label}).",
        )

    def convert(self, input_path: str, output_path: str):
        """
        Performs the data conversion from a CSV file to an XML file.
        """
        self.logger.info(f"Starting conversion of counseling data: {input_path}")

        try:
            with open(input_path, 'r', encoding='utf-8-sig') as csv_file:
                reader = csv.DictReader(csv_file)
                # CONV-2: normalize header whitespace so a stray/doubled space in a
                # column name can't silently break row.get() lookups downstream.
                rows = [data_cleaning.normalize_row_keys(row) for row in reader]
                self.logger.info(f"Successfully read CSV file with {len(rows)} records")
        except (OSError, csv.Error) as e:
            self.logger.error(f"Failed to read CSV file: {str(e)}")
            self.validator.add_issue("file", "error", ValidationCategory.FILE_ACCESS, "input_file", f"Failed to read CSV file: {str(e)}")
            raise

        if not rows:
            # CONV-6: a headers-only / empty CSV must fail, not silently produce
            # an empty <CounselingInformation/>.
            self.validator.add_issue("file", "error", ValidationCategory.MISSING_REQUIRED, "input_file", "CSV has headers but no data rows to convert.")
            raise EmptyCSVError("CSV has no data rows to convert.")

        root = ET.Element('CounselingInformation')
        processed_records = 0
        skipped_records = 0
        total_rows = len(rows)

        # Emit an initial "0 of N" tick so the progress bar anchors at
        # zero rather than an empty state while the first row runs.
        self._report_progress(0, total_rows)

        for row_index, row in enumerate(rows, 1):
            row = self._preprocess_row(row)
            record_id = row.get('Contact ID', f"Row_{row_index}")
            # Set before validate_counseling_record so pre-validation issues
            # (including missing-Contact-ID "Row_N" ones) carry the event id.
            self.validator.set_current_event_id(row.get('Activity ID', ''))
            # Reset per row so duplicate Contact IDs still warn independently.
            self._fabrication_warned.clear()

            if not data_validation.validate_counseling_record(row, row_index, self.validator):
                self.logger.warning(f"Skipping record {record_id} due to initial validation errors")
                skipped_records += 1
                self._maybe_report_progress(row_index, total_rows)
                continue

            try:
                counseling_record = create_element(root, 'CounselingRecord')
                create_element(counseling_record, 'PartnerClientNumber', record_id)

                location = create_element(counseling_record, 'Location')
                create_element(location, 'LocationCode', row.get('LocationCode', self.general_config.DEFAULT_LOCATION_CODE))

                self._build_client_request_section(counseling_record, row, record_id)
                self._build_client_intake_section(counseling_record, row, record_id)
                self._build_counselor_record_section(counseling_record, row, record_id)

                processed_records += 1
                self.validator.record_processed(success=True)

            except (ValueError, KeyError, AttributeError) as e:
                self.logger.error(f"Error processing record {record_id}: {str(e)}", exc_info=True)
                self.validator.add_issue(record_id, "error", ValidationCategory.PROCESSING_ERROR, "record", f"Error processing record: {str(e)}")
                self.validator.record_processed(success=False)

            self._maybe_report_progress(row_index, total_rows)

        # Final tick so the bar ends at 100% regardless of batch size.
        self._report_progress(total_rows, total_rows)

        # File-level issues below must not inherit the last row's event id.
        self.validator.set_current_event_id(None)

        try:
            tree = ET.ElementTree(root)
            ET.indent(tree, space="  ")
            tree.write(output_path, encoding='utf-8', xml_declaration=True)
            self.logger.info(f"XML file created successfully with {processed_records} records at {output_path}")
            if skipped_records > 0:
                self.logger.info(f"Skipped {skipped_records} records due to validation errors.")
        except OSError as e:
            self.logger.error(f"Failed to write XML file: {str(e)}")
            self.validator.add_issue("file", "error", ValidationCategory.FILE_WRITE, "output_file", f"Failed to write XML file: {str(e)}")
            raise

    def _build_client_request_section(self, parent, row, record_id):
        client_request = create_element(parent, 'ClientRequest')
        client_name = create_element(client_request, 'ClientNamePart1')
        create_element(client_name, 'Last', row.get('Last Name', ''))
        create_element(client_name, 'First', row.get('First Name', ''))
        emit_optional(client_name, 'Middle', row.get('Middle Name', ''))
        # Email is minOccurs="0" but pattern-constrained (EmailType), so a blank
        # cell must omit the element rather than emit <Email/>.
        emit_optional(client_request, 'Email', row.get('Email', ''))
        self._build_phone(client_request, 'PhonePart1', row)
        self._build_address(client_request, 'AddressPart1', row, record_id)
        # SurveyAgreement is required and YesNoType, so it can't be omitted:
        # a blank cell falls back to 'No'. `or` (not the .get default) so a
        # present-but-empty cell is treated the same as a missing column.
        create_element(client_request, 'SurveyAgreement',
                       (row.get('Agree to Impact Survey') or '').strip() or 'No')
        signature = create_element(client_request, 'ClientSignature')
        emit_optional(signature, 'Date', data_cleaning.format_date(row.get('Client Signature - Date', '')))
        signature_onfile = row.get('Client Signature(On File)', 'No')
        create_element(signature, 'OnFile', 'Yes' if signature_onfile in ['1', 1] else 'No')

    def _build_race(self, client_intake, row, record_id):
        race_element = create_element(client_intake, 'Race')
        race_codes = data_cleaning.split_multi_value(row.get('Race', ''))
        if race_codes:
            for code in race_codes:
                create_element(race_element, 'Code', code)
        else:
            create_element(race_element, 'Code', 'Prefer not to say')
            self.validator.add_issue(record_id, "warning", ValidationCategory.MISSING_FIELD, "Race", "Race missing, defaulted to 'Prefer not to say'.")

    def _build_demographics(self, client_intake, row):
        # Each of these is an XSD enumeration, so the raw CSV label has to be
        # mapped before it is emitted -- Salesforce exports "Not Hispanic or
        # Latino", which is not a member of the schema's enum.
        self._emit_mapped_enum(client_intake, 'Ethnicity', row.get('Ethnicity:', ''),
                               data_cleaning.map_ethnicity_to_xsd, row)
        self._emit_mapped_enum(client_intake, 'Sex', row.get('Gender', ''),
                               data_cleaning.map_gender_to_sex, row)
        self._emit_mapped_enum(client_intake, 'Disability', row.get('Disability', ''),
                               data_cleaning.map_disability_to_xsd, row)

    def _emit_mapped_enum(self, parent, element_name, raw_value, mapper, row):
        """Emit an enumerated element via `mapper`, omitting it when unmappable.

        An unrecognized value is dropped rather than passed through: one
        enum-invalid element fails validation for the entire document, and every
        element using this path is minOccurs="0".
        """
        mapped = mapper(raw_value)
        emit_optional(parent, element_name, mapped)
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
        if military_status_csv and military_status_csv.lower() not in non_military_statuses:
            branch_csv = row.get('Branch Of Service', '').strip()
            if branch_csv and branch_csv.lower() not in non_military_statuses:
                create_element(client_intake, 'BranchOfService', branch_csv)
            else:
                self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED, "BranchOfService", f"BranchOfService required for MilitaryStatus '{military_status_csv}' but is missing/invalid.")

    def _build_media_and_internet(self, client_intake, row, record_id):
        media_codes = data_cleaning.split_multi_value(row.get('What Prompted you to contact us?', ''))
        media_other = row.get('Internet (specify)', '').strip()
        if media_codes or media_other:
            media = create_element(client_intake, 'Media')
            for code in media_codes:
                create_element(media, 'Code', code)
            if media_other:
                create_element(media, 'Other', media_other)

        internet_usage = row.get('InternetUsage', '').strip()
        if internet_usage:
            create_element(client_intake, 'Internet', internet_usage)

        has_internet_media = any(c.strip().lower() == 'internet' for c in media_codes)
        if has_internet_media and not internet_usage and not media_other:
            self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED,
                "Internet", "Internet field should be mandatory when the media code is 'Internet'.")

    def _build_business_fields(self, client_intake, row, record_id):
        """Build business status, ownership, employees, and income fields. Returns in_business_val."""
        in_business_raw = row.get('Currently In Business?', '').strip()
        in_business_val = in_business_raw if in_business_raw in ('Yes', 'No', 'Undetermined') else self.general_config.DEFAULT_BUSINESS_STATUS
        in_business_val = self._resolve_in_business(in_business_val, row, record_id)
        create_element(client_intake, 'CurrentlyInBusiness', in_business_val)

        exporting_raw = row.get('Are you currently exporting?(old)', '').strip()
        exporting_val = exporting_raw if exporting_raw in ('Yes', 'No') else self.general_config.DEFAULT_BUSINESS_STATUS
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
        if data_cleaning.percentage_was_clamped(female_raw):
            # CONV-7: record the out-of-range original before clean_percentage clamps it.
            self.validator.add_issue(
                record_id, "warning", ValidationCategory.CLAMPED_VALUE,
                "BusinessOwnership/Female",
                f"% Female ownership '{str(female_raw).strip()}' is outside 0-100 "
                f"and was clamped to {female_ownership_val}.",
            )
        create_element(bo_element, 'Female', female_ownership_val)

        # Both of these are YesNoType (strictly Yes/No), so a present-but-blank
        # cell has to fall back to the default the same way a missing column
        # does -- `.get(key, default)` alone would leave '' and fail the enum.
        conducting_online = (row.get('Conduct Business Online?') or '').strip() or self.general_config.DEFAULT_BUSINESS_STATUS
        if data_cleaning.is_empty(row.get('Conduct Business Online?')) and conducting_online:
            self._warn_fabricated_default(record_id, 'Conduct Business Online?', conducting_online, 'Conducting Business Online')
        create_element(client_intake, 'ConductingBusinessOnline', conducting_online)
        certified_8a = (row.get('8(a) Certified?(old)') or '').strip() or self.general_config.DEFAULT_BUSINESS_STATUS
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
        total_emp_intake = data_cleaning.clean_numeric(row.get('Total Number of Employees', ''))
        if total_emp_intake:
            create_element(client_intake, 'TotalNumberOfEmployees', total_emp_intake)
        exporting_employees1 = data_cleaning.clean_numeric(row.get('Number of Employees in Exporting Business', ''))
        if exporting_employees1 and float(exporting_employees1) > 0:
            create_element(client_intake, 'NumberOfEmployeesInExportingBusiness', str(int(float(exporting_employees1))))

        income_part2 = create_element(client_intake, 'ClientAnnualIncomePart2')
        gross_rev = data_cleaning.clean_numeric(row.get('Gross Revenues/Sales', ''))
        if not gross_rev:
            self._warn_fabricated_default(record_id, 'Gross Revenues/Sales', '0', 'Gross Revenues')
        create_element(income_part2, 'GrossRevenues', gross_rev if gross_rev else '0')
        profit_loss = data_cleaning.clean_numeric(row.get('Profits/Losses', ''))
        if not profit_loss:
            self._warn_fabricated_default(record_id, 'Profits/Losses', '0', 'Profit/Loss')
        create_element(income_part2, 'ProfitLoss', profit_loss if profit_loss else '0')
        create_element(income_part2, 'ExportGrossRevenuesOrSales', '0')

        return in_business_val

    def _build_legal_entity(self, client_intake, row, record_id):
        le_element = create_element(client_intake, 'LegalEntity')
        le_codes = data_cleaning.split_multi_value(row.get('Legal Entity of Business', ''))
        le_other = row.get('Other legal entity (specify)', '').strip()
        if le_codes:
            for code in le_codes:
                create_element(le_element, 'Code', code)
        elif le_other:
            create_element(le_element, 'Code', 'Other')
        else:
            self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED, "LegalEntity", "Client is in business, but Legal Entity is missing.")
            create_element(le_element, 'Code', 'Other')
        if le_other:
            create_element(le_element, 'Other', le_other)

    def _build_rural_urban(self, client_intake, row, record_id):
        rural_urban_val = (row.get('Rural_vs_Urban') or '').strip() or self.config.DEFAULT_URBAN_RURAL
        create_element(client_intake, 'Rural_vs_Urban', rural_urban_val)

        if rural_urban_val.lower() in ['rural', 'urban']:
            fips_code = row.get('FIPS_Code', '').strip()
            if fips_code:
                create_element(client_intake, 'FIPS_Code', fips_code)
            else:
                self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED, "FIPS_Code", f"FIPS Code required for Rural/Urban status '{rural_urban_val}' but is missing.")

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
        if cs_codes or cs_other:
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
        self._build_demographics(client_intake, row)
        self._build_military_status(client_intake, row, record_id)
        self._build_media_and_internet(client_intake, row, record_id)
        in_business_val = self._build_business_fields(client_intake, row, record_id)
        if in_business_val.lower() == 'yes':
            self._build_legal_entity(client_intake, row, record_id)
        self._build_rural_urban(client_intake, row, record_id)
        self._build_counseling_seeking(client_intake, row, record_id, in_business_val)
        self._build_export_countries(client_intake, row, record_id)

    def _build_counselor_identity(self, counselor_record, row, record_id):
        create_element(counselor_record, 'PartnerSessionNumber', self._partner_session_number(row))

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
        self._build_phone(counselor_record, 'PhonePart3', row)
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

    def _build_business_verification(self, counselor_record, row):
        """Build business verification and reportable impact fields. Returns session-relevant values."""
        verified_in_business = row.get('Verified To Be In Business', 'Undetermined').strip()
        if verified_in_business not in ('Yes', 'No', 'Undetermined'):
            verified_in_business = 'Undetermined'

        reportable_raw = row.get('Reportable Impact', self.general_config.DEFAULT_BUSINESS_STATUS).strip()
        reportable_impact = reportable_raw if reportable_raw in ('Yes', 'No') else 'No'

        if reportable_impact == 'Yes' and verified_in_business != 'Yes':
            verified_in_business = 'Yes'

        create_element(counselor_record, 'VerifiedToBeInBusiness', verified_in_business)
        create_element(counselor_record, 'ReportableImpact', reportable_impact)

        impact_date = data_cleaning.format_date(row.get('Reportable Impact Date', ''))
        if impact_date:
            create_element(counselor_record, 'DateOfReportableImpact', impact_date)
        create_element(counselor_record, 'CurrentlyExporting', self.general_config.DEFAULT_BUSINESS_STATUS)

        business_start_date = data_cleaning.format_date(row.get('Business Start Date', '')) or data_cleaning.format_date(row.get('Date Started (Meeting)', ''))
        if business_start_date:
            create_element(counselor_record, 'BusinessStartDatePart3', business_start_date)

    def _build_financial_data(self, counselor_record, row, record_id):
        total_employees = data_cleaning.clean_numeric(row.get('Total No. of Employees (Meeting)', row.get('Total Number of Employees', '0')))
        if total_employees:
            create_element(counselor_record, 'TotalNumberOfEmployees', total_employees)

        exporting_employees2 = data_cleaning.clean_numeric(row.get('Number of Employees in Exporting Business', ''))
        if exporting_employees2 and float(exporting_employees2) > 0:
            create_element(counselor_record, 'NumberOfEmployeesInExportingBusiness', str(int(float(exporting_employees2))))

        gross_rev_part3 = data_cleaning.clean_numeric(row.get('Gross Revenues/Sales (Meeting)', row.get('Gross Revenues/Sales', '')))
        profit_loss_part3 = data_cleaning.clean_numeric(row.get('Profit & Loss (Meeting)', row.get('Profits/Losses', '')))
        income_part3 = create_element(counselor_record, 'ClientAnnualIncomePart3')
        # No fabrication warnings here for gross revenue / profit-loss: they are
        # keyed on the base columns (the "(Meeting)" variants are intentionally
        # excluded, see COUNSELING_FABRICATION_DEFAULTS) and Part 2 already warns
        # whenever the base column is blank, so warning again would be noise.
        create_element(income_part3, 'GrossRevenues', gross_rev_part3 if gross_rev_part3 else '0')
        create_element(income_part3, 'ProfitLoss', profit_loss_part3 if profit_loss_part3 else '0')
        create_element(income_part3, 'ExportGrossRevenuesOrSales', '0')

        # Default to '' (not '0') so an absent column is indistinguishable from a
        # blank cell here and both trip the fabrication warning; the emitted value
        # is unchanged because the create_element calls below fall back to '0'.
        sba_loan = data_cleaning.clean_numeric(row.get('SBA Loan Amount', ''))
        non_sba_loan = data_cleaning.clean_numeric(row.get('Non-SBA Loan Amount', ''))
        equity_capital = data_cleaning.clean_numeric(row.get('Amount of Equity Capital Received', ''))
        rpsc = create_element(counselor_record, 'ResourcePartnerServiceContributed')
        if not sba_loan:
            self._warn_fabricated_default(record_id, 'SBA Loan Amount', '0', 'SBA Loan Amount')
        create_element(rpsc, 'SBALoanAmount', sba_loan if sba_loan else '0')
        if not non_sba_loan:
            self._warn_fabricated_default(record_id, 'Non-SBA Loan Amount', '0', 'Non-SBA Loan Amount')
        create_element(rpsc, 'NonSBALoanAmount', non_sba_loan if non_sba_loan else '0')
        if not equity_capital:
            self._warn_fabricated_default(record_id, 'Amount of Equity Capital Received', '0', 'Equity Capital Received')
        create_element(rpsc, 'EquityCapitalReceived', equity_capital if equity_capital else '0')

    def _build_coded_section(self, parent, element_name, codes, other_text, default_other_code=None):
        """Build an optional section with Code elements and an Other field."""
        if not codes and not other_text:
            return
        element = create_element(parent, element_name)
        for code in codes:
            create_element(element, 'Code', code)
        if not codes and other_text and default_other_code:
            create_element(element, 'Code', default_other_code)
        if other_text:
            create_element(element, 'Other', other_text)

    def _build_counseling_provided(self, counselor_record, row, record_id):
        cp_element = create_element(counselor_record, 'CounselingProvided')
        # `or` rather than the .get default so a present-but-blank cell also
        # falls back -- CounselingProvided requires at least one Code.
        provided_codes = data_cleaning.split_multi_value(
            (row.get('Services Provided') or '').strip() or BUSINESS_STARTUP_PREPLANNING)
        provided_codes = self._cap_single_code(provided_codes, record_id, 'CounselingProvided',
                                               'Services Provided')
        has_other_code = any(c.strip().lower() == 'other' for c in provided_codes)
        provided_codes = ['Business Operations/Management' if c.strip().lower() == 'other' else c for c in provided_codes]
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
        if session_type not in self.config.VALID_SESSION_TYPES:
            self.validator.add_issue(record_id, "warning", ValidationCategory.INVALID_VALUE, "SessionType", f"Invalid session type '{session_type_raw}', defaulted.")
            session_type = self.config.DEFAULT_SESSION_TYPE
        create_element(counselor_record, 'SessionType', session_type)

        # Language requires at least one Code child, so a blank cell falls back
        # to the default language rather than producing an empty <Language/>.
        lang_codes = data_cleaning.split_multi_value(
            (row.get('Language(s) Used') or '').strip() or self.general_config.DEFAULT_LANGUAGE)
        lang_other = row.get('Language(s) Used (Other)', '').strip()
        if lang_codes or lang_other:
            lang_element = create_element(counselor_record, 'Language')
            for code in lang_codes:
                create_element(lang_element, 'Code', code)
            emit_optional(lang_element, 'Other', lang_other)

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
        emit_optional(ch_element, 'Contact', contact_val)
        emit_optional(ch_element, 'Prepare', data_cleaning.clean_numeric((row.get('Prep Hours') or '0')))
        emit_optional(ch_element, 'Travel', data_cleaning.clean_numeric((row.get('Travel Hours') or '0')))

        counselor_notes = data_cleaning.truncate_counselor_notes(row.get('Comments', ''), self.config.MAX_FIELD_LENGTHS["CounselorNotes"])
        if counselor_notes:
            create_element(counselor_record, 'CounselorNotes', counselor_notes)

    def _build_counselor_record_section(self, parent, row, record_id):
        counselor_record = create_element(parent, 'CounselorRecord')
        self._build_counselor_identity(counselor_record, row, record_id)
        self._build_business_verification(counselor_record, row)
        self._build_financial_data(counselor_record, row, record_id)

        self._build_coded_section(counselor_record, 'Certifications',
            data_cleaning.split_multi_value(row.get('Certifications (SDB, HUBZONE, etc)', '')),
            row.get('Other Certifications', '').strip(), 'Other')

        self._build_coded_section(counselor_record, 'SBAFinancialAssistance',
            data_cleaning.split_multi_value(row.get('SBA Financial Assistance', '')),
            row.get('Other SBA Financial Assistance', '').strip(), 'Other(SBIR, SBIC, 7(a) 504, etc)')

        self._build_counseling_provided(counselor_record, row, record_id)

        self._build_coded_section(counselor_record, 'ReferredClient',
            data_cleaning.split_multi_value(row.get('Referred Client to', '')),
            row.get('Other (Referred Client to)', '').strip(), 'Other')

        self._build_session_details(counselor_record, row, record_id)
        # Unused here; lets subclasses append trailing elements (e.g. TrainingSession).
        return counselor_record


    def _build_address(self, parent, element_name, row, record_id):
        address = create_element(parent, element_name)
        # Every child here is minOccurs="0", and State/ZipCode carry an
        # enumeration and a \d{5} pattern respectively -- so a blank cell must
        # omit the element, not emit an empty one (which fails validation).
        emit_optional(address, 'Street1', row.get('Mailing Street', ''))
        emit_optional(address, 'Street2', '')
        emit_optional(address, 'City', row.get('Mailing City', ''))
        emit_optional(address, 'State', data_cleaning.standardize_state_name(row.get('Mailing State/Province', '')))
        zip_full = str(row.get('Mailing Zip/Postal Code', '')).strip()
        zip_5digit_match = re.match(r'^\d{5}', zip_full)
        zip_5digit = zip_5digit_match.group(0) if zip_5digit_match else ''
        if not zip_5digit and zip_full:
            self.validator.add_issue(record_id, "warning", ValidationCategory.INVALID_FORMAT, "Mailing Zip/Postal Code", f"Could not parse 5-digit ZIP from '{zip_full}'.")
        emit_optional(address, 'ZipCode', zip_5digit)
        # Zip4Code requires exactly 4 digits per XSD - only emit if we have it
        zip4_match = re.match(r'^\d{5}-(\d{4})', zip_full)
        if zip4_match:
            create_element(address, 'Zip4Code', zip4_match.group(1))
        country = create_element(address, 'Country')
        country_val = data_cleaning.standardize_country_code(row.get('Mailing Country', 'US'))
        if data_cleaning.is_empty(row.get('Mailing Country')):
            # Deduped per (record, field): the address is built for both
            # AddressPart1 and AddressPart3 but only one warning is recorded.
            self._warn_fabricated_default(record_id, 'Mailing Country', country_val, 'Mailing Country')
        create_element(country, 'Code', country_val)

    def _build_phone(self, parent, element_name, row):
        primary_phone = data_cleaning.clean_phone_number(row.get('Contact: Phone', ''))
        secondary_phone = data_cleaning.clean_phone_number(row.get('Contact: Secondary Phone', ''))
        # Only emit phone element if at least one number is present
        if primary_phone or secondary_phone:
            phone = create_element(parent, element_name)
            if primary_phone:
                create_element(phone, 'Primary', primary_phone)
            if secondary_phone:
                create_element(phone, 'Secondary', secondary_phone)
