"""
Handles the conversion of Salesforce counseling data (Form 641) from CSV to XML.
"""

import csv
import xml.etree.ElementTree as ET
import re

from .base_converter import BaseConverter
from ..config import CounselingConfig, GeneralConfig, ValidationCategory
from .. import data_cleaning
from .. import data_validation
from ..xml_utils import create_element

class CounselingConverter(BaseConverter):
    """
    Converter for Counseling (Form 641) data.
    """
    def __init__(self, logger, validator):
        super().__init__(logger, validator)
        self.config = CounselingConfig()
        self.general_config = GeneralConfig()

    def _preprocess_row(self, row):
        """Hook for subclasses to transform a row before processing. Returns the row unchanged by default."""
        return row

    def convert(self, input_path: str, output_path: str):
        """
        Performs the data conversion from a CSV file to an XML file.
        """
        self.logger.info(f"Starting conversion of counseling data: {input_path}")

        try:
            with open(input_path, 'r', encoding='utf-8-sig') as csv_file:
                reader = csv.DictReader(csv_file)
                rows = list(reader)
                self.logger.info(f"Successfully read CSV file with {len(rows)} records")
        except (OSError, csv.Error) as e:
            self.logger.error(f"Failed to read CSV file: {str(e)}")
            self.validator.add_issue("file", "error", ValidationCategory.FILE_ACCESS, "input_file", f"Failed to read CSV file: {str(e)}")
            raise

        root = ET.Element('CounselingInformation')
        processed_records = 0
        skipped_records = 0

        for row_index, row in enumerate(rows, 1):
            row = self._preprocess_row(row)
            record_id = row.get('Contact ID', f"Row_{row_index}")

            if not data_validation.validate_counseling_record(row, row_index, self.validator):
                self.logger.warning(f"Skipping record {record_id} due to initial validation errors")
                skipped_records += 1
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
        create_element(client_name, 'Middle', row.get('Middle Name', ''))
        create_element(client_request, 'Email', row.get('Email', ''))
        self._build_phone(client_request, 'PhonePart1', row)
        self._build_address(client_request, 'AddressPart1', row, record_id)
        create_element(client_request, 'SurveyAgreement', row.get('Agree to Impact Survey', 'No'))
        signature = create_element(client_request, 'ClientSignature')
        create_element(signature, 'Date', data_cleaning.format_date(row.get('Client Signature - Date', '')))
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
        ethnicity_csv = row.get('Ethnicity:', '').strip()
        if ethnicity_csv:
            create_element(client_intake, 'Ethnicity', ethnicity_csv)

        sex_value = data_cleaning.map_gender_to_sex(row.get('Gender', ''))
        if sex_value:
            create_element(client_intake, 'Sex', sex_value)

        disability_csv = row.get('Disability', '').strip()
        if disability_csv:
            create_element(client_intake, 'Disability', disability_csv)

    def _build_military_status(self, client_intake, row, record_id):
        military_status_csv = row.get('Veteran Status', '').strip()
        if military_status_csv:
            create_element(client_intake, 'MilitaryStatus', military_status_csv)

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

    def _build_business_fields(self, client_intake, row):
        """Build business status, ownership, employees, and income fields. Returns in_business_val."""
        in_business_raw = row.get('Currently In Business?', '').strip()
        in_business_val = in_business_raw if in_business_raw in ('Yes', 'No', 'Undetermined') else self.general_config.DEFAULT_BUSINESS_STATUS
        create_element(client_intake, 'CurrentlyInBusiness', in_business_val)

        exporting_raw = row.get('Are you currently exporting?(old)', '').strip()
        exporting_val = exporting_raw if exporting_raw in ('Yes', 'No') else self.general_config.DEFAULT_BUSINESS_STATUS
        create_element(client_intake, 'CurrentlyExporting', exporting_val)

        create_element(client_intake, 'CompanyName', row.get('Account Name', ''))
        business_type = row.get('Type of Business', '').strip()
        if business_type:
            create_element(client_intake, 'BusinessType', business_type)

        bo_element = create_element(client_intake, 'BusinessOwnership')
        female_ownership_val = data_cleaning.clean_percentage(row.get('Business Ownership - % Female(old)', '0'))
        create_element(bo_element, 'Female', female_ownership_val)

        create_element(client_intake, 'ConductingBusinessOnline', row.get('Conduct Business Online?', self.general_config.DEFAULT_BUSINESS_STATUS))
        create_element(client_intake, 'ClientIntake_Certified8a', row.get('8(a) Certified?(old)', self.general_config.DEFAULT_BUSINESS_STATUS))
        total_emp_intake = data_cleaning.clean_numeric(row.get('Total Number of Employees', ''))
        if total_emp_intake:
            create_element(client_intake, 'TotalNumberOfEmployees', total_emp_intake)
        exporting_employees1 = data_cleaning.clean_numeric(row.get('Number of Employees in Exporting Business', ''))
        if exporting_employees1 and float(exporting_employees1) > 0:
            create_element(client_intake, 'NumberOfEmployeesInExportingBusiness', str(int(float(exporting_employees1))))

        income_part2 = create_element(client_intake, 'ClientAnnualIncomePart2')
        gross_rev = data_cleaning.clean_numeric(row.get('Gross Revenues/Sales', ''))
        create_element(income_part2, 'GrossRevenues', gross_rev if gross_rev else '0')
        profit_loss = data_cleaning.clean_numeric(row.get('Profits/Losses', ''))
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
        rural_urban_val = row.get('Rural_vs_Urban', self.config.DEFAULT_URBAN_RURAL)
        create_element(client_intake, 'Rural_vs_Urban', rural_urban_val)

        if rural_urban_val.lower() in ['rural', 'urban']:
            fips_code = row.get('FIPS_Code', '').strip()
            if fips_code:
                create_element(client_intake, 'FIPS_Code', fips_code)
            else:
                self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED, "FIPS_Code", f"FIPS Code required for Rural/Urban status '{rural_urban_val}' but is missing.")

    def _build_counseling_seeking(self, client_intake, row, record_id, in_business_val):
        cs_codes = data_cleaning.split_multi_value(row.get('Nature of the Counseling Seeking?', ''))
        cs_other = row.get('Nature of the Counseling Seeking - Other Detail', '').strip()
        if cs_codes or cs_other:
            cs_element = create_element(client_intake, 'CounselingSeeking')
            is_other_present = any(c.lower() == 'other' for c in cs_codes)
            for code in cs_codes:
                create_element(cs_element, 'Code', code)
            if is_other_present and not cs_other:
                self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED, "CounselingSeeking/Other", "CounselingSeeking is 'Other' but detail text is missing.")
            create_element(cs_element, 'Other', cs_other)

        if in_business_val == 'Yes' and not cs_codes:
            self.validator.add_issue(record_id, "error", ValidationCategory.MISSING_REQUIRED,
                "CounselingSeeking", "Counseling Seeking is required under Part 2 if Client is in Business.")

    def _build_client_intake_section(self, parent, row, record_id):
        client_intake = create_element(parent, 'ClientIntake')
        self._build_race(client_intake, row, record_id)
        self._build_demographics(client_intake, row)
        self._build_military_status(client_intake, row, record_id)
        self._build_media_and_internet(client_intake, row, record_id)
        in_business_val = self._build_business_fields(client_intake, row)
        if in_business_val.lower() == 'yes':
            self._build_legal_entity(client_intake, row, record_id)
        self._build_rural_urban(client_intake, row, record_id)
        self._build_counseling_seeking(client_intake, row, record_id, in_business_val)

    def _build_counselor_identity(self, counselor_record, row, record_id):
        create_element(counselor_record, 'PartnerSessionNumber', row.get('Activity ID', ''))

        funding_source = row.get('Funding Source', '').strip()
        if funding_source:
            create_element(counselor_record, 'FundingSource', funding_source)

        counselor_name_part3 = create_element(counselor_record, 'ClientNamePart3')
        create_element(counselor_name_part3, 'Last', row.get('Last Name', ''))
        create_element(counselor_name_part3, 'First', row.get('First Name', ''))
        create_element(counselor_name_part3, 'Middle', row.get('Middle Name', ''))

        create_element(counselor_record, 'Email', row.get('Email', ''))
        self._build_phone(counselor_record, 'PhonePart3', row)
        self._build_address(counselor_record, 'AddressPart3', row, record_id)

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

    def _build_financial_data(self, counselor_record, row):
        total_employees = data_cleaning.clean_numeric(row.get('Total No. of Employees (Meeting)', row.get('Total Number of Employees', '0')))
        if total_employees:
            create_element(counselor_record, 'TotalNumberOfEmployees', total_employees)

        exporting_employees2 = data_cleaning.clean_numeric(row.get('Number of Employees in Exporting Business', ''))
        if exporting_employees2 and float(exporting_employees2) > 0:
            create_element(counselor_record, 'NumberOfEmployeesInExportingBusiness', str(int(float(exporting_employees2))))

        gross_rev_part3 = data_cleaning.clean_numeric(row.get('Gross Revenues/Sales (Meeting)', row.get('Gross Revenues/Sales', '')))
        profit_loss_part3 = data_cleaning.clean_numeric(row.get('Profit & Loss (Meeting)', row.get('Profits/Losses', '')))
        income_part3 = create_element(counselor_record, 'ClientAnnualIncomePart3')
        create_element(income_part3, 'GrossRevenues', gross_rev_part3 if gross_rev_part3 else '0')
        create_element(income_part3, 'ProfitLoss', profit_loss_part3 if profit_loss_part3 else '0')
        create_element(income_part3, 'ExportGrossRevenuesOrSales', '0')

        sba_loan = data_cleaning.clean_numeric(row.get('SBA Loan Amount', '0'))
        non_sba_loan = data_cleaning.clean_numeric(row.get('Non-SBA Loan Amount', '0'))
        equity_capital = data_cleaning.clean_numeric(row.get('Amount of Equity Capital Received', '0'))
        rpsc = create_element(counselor_record, 'ResourcePartnerServiceContributed')
        create_element(rpsc, 'SBALoanAmount', sba_loan if sba_loan else '0')
        create_element(rpsc, 'NonSBALoanAmount', non_sba_loan if non_sba_loan else '0')
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
        provided_codes = data_cleaning.split_multi_value(row.get('Services Provided', 'Business Start-up/Preplanning'))
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

        lang_element = create_element(counselor_record, 'Language')
        for code in data_cleaning.split_multi_value(row.get('Language(s) Used', self.general_config.DEFAULT_LANGUAGE)):
            create_element(lang_element, 'Code', code)
        lang_other = row.get('Language(s) Used (Other)', '').strip()
        if lang_other:
            create_element(lang_element, 'Other', lang_other)

        date_counseled = data_cleaning.format_date(row.get('Date', ''))
        if date_counseled:
            create_element(counselor_record, 'DateCounseled', date_counseled)

        counselor_name = row.get('Name of Counselor', '').strip()
        if counselor_name:
            create_element(counselor_record, 'CounselorName', counselor_name)

        ch_element = create_element(counselor_record, 'CounselingHours')
        contact_val = data_cleaning.clean_numeric(row.get('Duration (hours)', '0'))
        if session_type not in self.config.NO_CONTACT_HOUR_SESSION_TYPES and float(contact_val or 0) <= 0:
            contact_val = "0.5"
        create_element(ch_element, 'Contact', contact_val)
        create_element(ch_element, 'Prepare', data_cleaning.clean_numeric(row.get('Prep Hours', '0')))
        create_element(ch_element, 'Travel', data_cleaning.clean_numeric(row.get('Travel Hours', '0')))

        counselor_notes = data_cleaning.truncate_counselor_notes(row.get('Comments', ''), self.config.MAX_FIELD_LENGTHS["CounselorNotes"])
        if counselor_notes:
            create_element(counselor_record, 'CounselorNotes', counselor_notes)

    def _build_counselor_record_section(self, parent, row, record_id):
        counselor_record = create_element(parent, 'CounselorRecord')
        self._build_counselor_identity(counselor_record, row, record_id)
        self._build_business_verification(counselor_record, row)
        self._build_financial_data(counselor_record, row)

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


    def _build_address(self, parent, element_name, row, record_id):
        address = create_element(parent, element_name)
        create_element(address, 'Street1', row.get('Mailing Street', ''))
        create_element(address, 'Street2', '')
        create_element(address, 'City', row.get('Mailing City', ''))
        create_element(address, 'State', data_cleaning.standardize_state_name(row.get('Mailing State/Province', '')))
        zip_full = str(row.get('Mailing Zip/Postal Code', '')).strip()
        zip_5digit_match = re.match(r'^\d{5}', zip_full)
        zip_5digit = zip_5digit_match.group(0) if zip_5digit_match else ''
        if not zip_5digit and zip_full:
            self.validator.add_issue(record_id, "warning", ValidationCategory.INVALID_FORMAT, "Mailing Zip/Postal Code", f"Could not parse 5-digit ZIP from '{zip_full}'.")
        create_element(address, 'ZipCode', zip_5digit)
        # Zip4Code requires exactly 4 digits per XSD - only emit if we have it
        zip4_match = re.match(r'^\d{5}-(\d{4})', zip_full)
        if zip4_match:
            create_element(address, 'Zip4Code', zip4_match.group(1))
        country = create_element(address, 'Country')
        create_element(country, 'Code', data_cleaning.standardize_country_code(row.get('Mailing Country', 'US')))

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
