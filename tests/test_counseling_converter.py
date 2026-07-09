import unittest
import os
import sys
import tempfile
import csv
import xml.etree.ElementTree as ET

from lxml import etree

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.converters.counseling_converter import CounselingConverter
from src.logging_util import ConversionLogger
from src.validation_report import ValidationTracker

COUNSELING_XSD = os.path.join(os.path.dirname(__file__), '..', 'schemas', 'SBA_NEXUS_Counseling-2-14.xsd')

class TestCounselingConverter(unittest.TestCase):

    def setUp(self):
        self.logger = ConversionLogger("test_counseling", log_level="DEBUG", log_to_file=False).logger
        self.validator = ValidationTracker()

    def test_converter_instantiation(self):
        converter = CounselingConverter(self.logger, self.validator)
        self.assertIsInstance(converter, CounselingConverter)

    def _write_csv(self, rows, fieldnames=None):
        """Helper to write a CSV to a temp file and return the path."""
        if fieldnames is None:
            fieldnames = rows[0].keys() if rows else []
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='', encoding='utf-8')
        writer = csv.DictWriter(tmp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        tmp.close()
        return tmp.name

    def _make_valid_row(self, **overrides):
        """Return a minimal valid counseling row dict with optional overrides."""
        base = {
            'Contact ID': 'C-001',
            'Last Name': 'Smith',
            'First Name': 'John',
            'Middle Name': '',
            'Email': 'john@example.com',
            'Contact: Phone': '(515) 555-1234',
            'Contact: Secondary Phone': '',
            'Mailing Street': '123 Main St',
            'Mailing City': 'Des Moines',
            'Mailing State/Province': 'IA',
            'Mailing Zip/Postal Code': '50309',
            'Mailing Country': 'US',
            'Agree to Impact Survey': 'Yes',
            'Client Signature - Date': '2025-01-15',
            'Client Signature(On File)': '1',
            'Race': 'White',
            'Ethnicity:': 'Non-Hispanic',
            'Gender': 'Male',
            'Disability': '',
            'Veteran Status': '',
            'Branch Of Service': '',
            'What Prompted you to contact us?': '',
            'Internet (specify)': '',
            'InternetUsage': '',
            'Currently In Business?': 'No',
            'Are you currently exporting?(old)': 'No',
            'Account Name': '',
            'Type of Business': '',
            'Business Ownership - % Female(old)': '0',
            'Conduct Business Online?': 'No',
            '8(a) Certified?(old)': 'No',
            'Total Number of Employees': '',
            'Number of Employees in Exporting Business': '',
            'Gross Revenues/Sales': '',
            'Profits/Losses': '',
            'Rural_vs_Urban': 'Undetermined',
            'FIPS_Code': '',
            'Nature of the Counseling Seeking?': '',
            'Nature of the Counseling Seeking - Other Detail': '',
            'Activity ID': 'A-001',
            'Funding Source': 'WBC',
            'LocationCode': '249003',
            'Verified To Be In Business': 'No',
            'Reportable Impact': 'No',
            'Reportable Impact Date': '',
            'Business Start Date': '',
            'Date Started (Meeting)': '',
            'Total No. of Employees (Meeting)': '',
            'Gross Revenues/Sales (Meeting)': '',
            'Profit & Loss (Meeting)': '',
            'SBA Loan Amount': '0',
            'Non-SBA Loan Amount': '0',
            'Amount of Equity Capital Received': '0',
            'Certifications (SDB, HUBZONE, etc)': '',
            'Other Certifications': '',
            'SBA Financial Assistance': '',
            'Other SBA Financial Assistance': '',
            'Services Provided': 'Business Start-up/Preplanning',
            'Other Counseling Provided': '',
            'Referred Client to': '',
            'Other (Referred Client to)': '',
            'Type of Session': 'Telephone',
            'Language(s) Used': 'English',
            'Language(s) Used (Other)': '',
            'Date': '2025-01-15',
            'Name of Counselor': 'Jane Doe',
            'Duration (hours)': '1.5',
            'Prep Hours': '0.5',
            'Travel Hours': '0',
            'Comments': 'Initial consultation.',
            'Legal Entity of Business': '',
            'Other legal entity (specify)': '',
        }
        base.update(overrides)
        return base

    def _convert_and_parse(self, rows):
        """Convert rows to XML and return parsed root element."""
        csv_path = self._write_csv(rows)
        xml_path = tempfile.NamedTemporaryFile(suffix='.xml', delete=False).name
        try:
            converter = CounselingConverter(self.logger, self.validator)
            converter.convert(csv_path, xml_path)
            tree = ET.parse(xml_path)
            return tree.getroot()
        finally:
            os.unlink(csv_path)
            if os.path.exists(xml_path):
                os.unlink(xml_path)

    def _convert_validate_and_parse(self, rows):
        """Convert rows to XML, assert the output validates against the real
        counseling XSD, and return the parsed root element."""
        csv_path = self._write_csv(rows)
        xml_path = tempfile.NamedTemporaryFile(suffix='.xml', delete=False).name
        try:
            converter = CounselingConverter(self.logger, self.validator)
            converter.convert(csv_path, xml_path)
            parser = etree.XMLParser(resolve_entities=False)
            schema = etree.XMLSchema(etree.parse(COUNSELING_XSD, parser=parser))
            is_valid = schema.validate(etree.parse(xml_path, parser=parser))
            self.assertTrue(is_valid, "XSD validation errors:\n" + "\n".join(str(e) for e in schema.error_log[:10]))
            return ET.parse(xml_path).getroot()
        finally:
            os.unlink(csv_path)
            if os.path.exists(xml_path):
                os.unlink(xml_path)

    def test_basic_conversion_produces_valid_xml(self):
        """Test that a valid row produces a CounselingRecord element."""
        root = self._convert_and_parse([self._make_valid_row()])
        records = root.findall('CounselingRecord')
        self.assertEqual(len(records), 1)

        record = records[0]
        self.assertEqual(record.find('PartnerClientNumber').text, 'C-001')
        self.assertEqual(record.find('Location/LocationCode').text, '249003')

    def test_client_request_section(self):
        """Test ClientRequest section has expected name and address fields."""
        root = self._convert_and_parse([self._make_valid_row()])
        cr = root.find('CounselingRecord/ClientRequest')
        self.assertIsNotNone(cr)
        self.assertEqual(cr.find('ClientNamePart1/Last').text, 'Smith')
        self.assertEqual(cr.find('ClientNamePart1/First').text, 'John')
        self.assertEqual(cr.find('Email').text, 'john@example.com')

    def test_address_state_standardized(self):
        """Test that state abbreviation is expanded to full name."""
        root = self._convert_and_parse([self._make_valid_row()])
        state = root.find('CounselingRecord/ClientRequest/AddressPart1/State')
        self.assertEqual(state.text, 'Iowa')

    def test_phone_number_cleaned(self):
        """Test that phone numbers are cleaned to digits only."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Contact: Phone': '+1 (515) 555-1234',
        })])
        phone = root.find('CounselingRecord/ClientRequest/PhonePart1/Primary')
        self.assertIsNotNone(phone)
        self.assertEqual(len(phone.text), 10)
        self.assertTrue(phone.text.isdigit())

    def test_missing_contact_id_skips_record(self):
        """Records without Contact ID should be skipped."""
        row = self._make_valid_row()
        row['Contact ID'] = ''
        root = self._convert_and_parse([row])
        records = root.findall('CounselingRecord')
        self.assertEqual(len(records), 0)

    def test_multiple_records_converted(self):
        """Test that multiple rows produce multiple records."""
        rows = [
            self._make_valid_row(**{'Contact ID': 'C-001'}),
            self._make_valid_row(**{'Contact ID': 'C-002', 'Last Name': 'Doe'}),
        ]
        root = self._convert_and_parse(rows)
        records = root.findall('CounselingRecord')
        self.assertEqual(len(records), 2)

    def test_race_defaults_to_prefer_not_to_say(self):
        """Missing race defaults to 'Prefer not to say'."""
        root = self._convert_and_parse([self._make_valid_row(Race='')])
        race_codes = root.findall('CounselingRecord/ClientIntake/Race/Code')
        self.assertEqual(len(race_codes), 1)
        self.assertEqual(race_codes[0].text, 'Prefer not to say')

    def test_in_business_creates_legal_entity(self):
        """When in business, LegalEntity section should be present."""
        row = self._make_valid_row(**{
            'Currently In Business?': 'Yes',
            'Legal Entity of Business': 'LLC',
        })
        root = self._convert_and_parse([row])
        le = root.find('CounselingRecord/ClientIntake/LegalEntity')
        self.assertIsNotNone(le)
        self.assertEqual(le.find('Code').text, 'LLC')

    def test_not_in_business_no_legal_entity(self):
        """When not in business, LegalEntity section should not exist."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Currently In Business?': 'No',
        })])
        le = root.find('CounselingRecord/ClientIntake/LegalEntity')
        self.assertIsNone(le)

    def test_in_business_missing_details_still_errors(self):
        """Counseling rows keep the strict behavior: 'Yes' with no legal entity
        or counseling seeking stays 'Yes' and raises both required-field errors
        (only the training-client converter downgrades to 'No')."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Currently In Business?': 'Yes',
        })])
        cib = root.find('CounselingRecord/ClientIntake/CurrentlyInBusiness')
        self.assertEqual(cib.text, 'Yes')
        error_fields = {i['field_name'] for i in self.validator.issues if i['severity'] == 'error'}
        self.assertIn('LegalEntity', error_fields)
        self.assertIn('CounselingSeeking', error_fields)
        downgraded = [i for i in self.validator.issues if i['category'] == 'downgraded_value']
        self.assertEqual(downgraded, [])

    def test_session_type_validation(self):
        """Invalid session type should be defaulted and tracked."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Type of Session': 'InvalidType',
        })])
        st = root.find('CounselingRecord/CounselorRecord/SessionType')
        self.assertEqual(st.text, 'Telephone')  # default
        # Check that a warning was recorded
        warnings = [i for i in self.validator.issues if i['severity'] == 'warning' and 'SessionType' in i['field_name']]
        self.assertTrue(len(warnings) > 0)

    def test_special_characters_in_text(self):
        """XML special characters in CSV data should be handled safely."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Last Name': 'O\'Brien & Associates',
            'Comments': 'Client said <urgent> & "important"',
        })])
        last = root.find('CounselingRecord/ClientRequest/ClientNamePart1/Last')
        self.assertEqual(last.text, "O'Brien & Associates")
        notes = root.find('CounselingRecord/CounselorRecord/CounselorNotes')
        self.assertIn('&', notes.text)

    def test_zip_code_parsing(self):
        """ZIP+4 codes should be parsed into ZipCode and Zip4Code."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Mailing Zip/Postal Code': '50309-1234',
        })])
        addr = root.find('CounselingRecord/ClientRequest/AddressPart1')
        self.assertEqual(addr.find('ZipCode').text, '50309')
        self.assertEqual(addr.find('Zip4Code').text, '1234')

    def test_country_standardized(self):
        """Country code should be standardized."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Mailing Country': 'USA',
        })])
        country = root.find('CounselingRecord/ClientRequest/AddressPart1/Country/Code')
        self.assertEqual(country.text, 'United States')

    def test_ambiguous_date_emitted_month_first_and_warned(self):
        """CONV-3: an ambiguous Date is emitted month-first AND flagged as a warning."""
        root = self._convert_and_parse([self._make_valid_row(**{'Date': '03/04/2025'})])
        date_el = root.find('CounselingRecord/CounselorRecord/DateCounseled')
        self.assertEqual(date_el.text, '2025-03-04')
        cats = [i['category'] for i in self.validator.issues]
        self.assertIn('ambiguous_date', cats)

    def test_unambiguous_date_records_no_warning(self):
        """CONV-3: an unambiguous ISO Date records no ambiguity warning."""
        self._convert_and_parse([self._make_valid_row(**{'Date': '2025-03-04'})])
        cats = [i['category'] for i in self.validator.issues]
        self.assertNotIn('ambiguous_date', cats)

    def test_percentage_over_100_clamped_and_warned(self):
        """CONV-7: a >100 % Female value is clamped to 100 AND flagged."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Business Ownership - % Female(old)': '150',
        })])
        female = root.find('CounselingRecord/ClientIntake/BusinessOwnership/Female')
        self.assertEqual(female.text, '100')
        cats = [i['category'] for i in self.validator.issues]
        self.assertIn('clamped_value', cats)

    def test_header_whitespace_tolerated(self):
        """CONV-2: a column whose header has stray whitespace is still matched."""
        base = self._make_valid_row()
        row = {(k + ' ' if k == 'Contact ID' else k): v for k, v in base.items()}
        root = self._convert_and_parse([row])
        num = root.find('CounselingRecord/PartnerClientNumber')
        self.assertEqual(num.text, 'C-001')  # not the 'Row_1' fallback

    # --- Per-row blank-cell fabrication warnings (plan 1.3) ---

    def _fabrication_issues(self, field_name=None):
        """Return recorded fabricated_default issues, optionally for one field."""
        issues = [i for i in self.validator.issues if i['category'] == 'fabricated_default']
        if field_name is not None:
            issues = [i for i in issues if i['field_name'] == field_name]
        return issues

    def test_blank_gross_revenue_defaults_to_zero_and_warns(self):
        """A blank Gross Revenues/Sales cell still emits '0' but records a warning."""
        root = self._convert_and_parse([self._make_valid_row(**{'Gross Revenues/Sales': ''})])
        gross = root.find('CounselingRecord/ClientIntake/ClientAnnualIncomePart2/GrossRevenues')
        self.assertEqual(gross.text, '0')
        issues = self._fabrication_issues('Gross Revenues/Sales')
        self.assertEqual(len(issues), 1)  # one per (record, field), Part 2/3 deduped
        self.assertEqual(issues[0]['record_id'], 'C-001')
        self.assertEqual(issues[0]['severity'], 'warning')
        self.assertIn("Blank value defaulted to '0'", issues[0]['message'])

    def test_populated_gross_revenue_records_no_fabrication_warning(self):
        """A populated Gross Revenues/Sales cell records no fabrication warning."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Gross Revenues/Sales': '50000',
            'Gross Revenues/Sales (Meeting)': '50000',
        })])
        gross = root.find('CounselingRecord/ClientIntake/ClientAnnualIncomePart2/GrossRevenues')
        self.assertEqual(gross.text, '50000')
        self.assertEqual(self._fabrication_issues('Gross Revenues/Sales'), [])

    def test_blank_mailing_country_warns_once_per_record(self):
        """A blank Mailing Country fabricates 'United States' in both address
        sections (Part 1 and Part 3) but records exactly one warning."""
        root = self._convert_and_parse([self._make_valid_row(**{'Mailing Country': ''})])
        country = root.find('CounselingRecord/ClientRequest/AddressPart1/Country/Code')
        self.assertEqual(country.text, 'United States')
        issues = self._fabrication_issues('Mailing Country')
        self.assertEqual(len(issues), 1)
        self.assertIn("Blank value defaulted to 'United States'", issues[0]['message'])

    def test_populated_mailing_country_records_no_fabrication_warning(self):
        self._convert_and_parse([self._make_valid_row(**{'Mailing Country': 'US'})])
        self.assertEqual(self._fabrication_issues('Mailing Country'), [])

    def test_blank_loan_amounts_warn_per_field(self):
        """Blank loan/equity cells each record their own fabrication warning."""
        self._convert_and_parse([self._make_valid_row(**{
            'SBA Loan Amount': '',
            'Non-SBA Loan Amount': '',
            'Amount of Equity Capital Received': '',
        })])
        self.assertEqual(len(self._fabrication_issues('SBA Loan Amount')), 1)
        self.assertEqual(len(self._fabrication_issues('Non-SBA Loan Amount')), 1)
        self.assertEqual(len(self._fabrication_issues('Amount of Equity Capital Received')), 1)

    # --- Employee_Owned and ExportCountries emission (plan 1.4) ---

    def test_employee_owned_emitted_when_affirmative(self):
        root = self._convert_and_parse([self._make_valid_row(**{'Employee Owned': 'Yes'})])
        eo = root.find('CounselingRecord/ClientIntake/Employee_Owned')
        self.assertIsNotNone(eo)
        self.assertEqual(eo.text, 'Yes')

    def test_employee_owned_negative_mapped_to_no(self):
        root = self._convert_and_parse([self._make_valid_row(**{'Employee Owned': 'false'})])
        eo = root.find('CounselingRecord/ClientIntake/Employee_Owned')
        self.assertIsNotNone(eo)
        self.assertEqual(eo.text, 'No')

    def test_employee_owned_omitted_when_blank_or_absent(self):
        """No Employee_Owned element (and no fabrication) for blank or absent input."""
        root = self._convert_and_parse([self._make_valid_row(**{'Employee Owned': ''})])
        self.assertIsNone(root.find('CounselingRecord/ClientIntake/Employee_Owned'))
        # Column absent entirely (the base row has no 'Employee Owned' key)
        root = self._convert_and_parse([self._make_valid_row()])
        self.assertIsNone(root.find('CounselingRecord/ClientIntake/Employee_Owned'))

    def test_export_countries_emitted_and_standardized(self):
        """Multi-value Export Countries are split and country codes expanded."""
        root = self._convert_and_parse([self._make_valid_row(**{'Export Countries': 'Belgium; US'})])
        codes = [e.text for e in root.findall('CounselingRecord/ClientIntake/ExportCountries/Code')]
        self.assertEqual(codes, ['Belgium', 'United States'])

    def test_export_countries_omitted_when_blank_or_absent(self):
        root = self._convert_and_parse([self._make_valid_row(**{'Export Countries': ''})])
        self.assertIsNone(root.find('CounselingRecord/ClientIntake/ExportCountries'))
        root = self._convert_and_parse([self._make_valid_row()])
        self.assertIsNone(root.find('CounselingRecord/ClientIntake/ExportCountries'))

    # --- ExportCountries enum resolution (enum-invalid Code values fail XSD
    # validation for the whole document, so only canonical spellings from
    # config.EXPORT_COUNTRY_CODES may ever be emitted) ---

    def _export_country_warnings(self):
        """Return the invalid_value warnings recorded for 'Export Countries'."""
        return [i for i in self.validator.issues
                if i['category'] == 'invalid_value' and i['field_name'] == 'Export Countries']

    def _make_xsd_valid_row(self, **overrides):
        """Like _make_valid_row, but with the base values the converter emits
        verbatim ('Funding Source', 'Ethnicity:') replaced by XSD-enum-valid
        ones, so the whole document can validate against the real schema."""
        row = self._make_valid_row(**{'Funding Source': '', 'Ethnicity:': 'Non Hispanic or Latino'})
        row.update(overrides)
        return row

    def test_export_countries_resolve_to_canonical_and_validate(self):
        """Standardized values resolve to canonical enum spellings and the
        output validates against the real XSD."""
        root = self._convert_validate_and_parse([self._make_xsd_valid_row(**{
            'Export Countries': 'US;United Kingdom'})])
        codes = [e.text for e in root.findall('CounselingRecord/ClientIntake/ExportCountries/Code')]
        self.assertEqual(codes, ['United States', 'United Kingdom'])
        self.assertEqual(self._export_country_warnings(), [])

    def test_export_countries_mixed_valid_and_invalid(self):
        """A value not in the enum is omitted with a warning; valid values still emit."""
        root = self._convert_validate_and_parse([self._make_xsd_valid_row(**{
            'Export Countries': 'US;Atlantis'})])
        codes = [e.text for e in root.findall('CounselingRecord/ClientIntake/ExportCountries/Code')]
        self.assertEqual(codes, ['United States'])
        warnings = self._export_country_warnings()
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]['severity'], 'warning')
        self.assertEqual(warnings[0]['record_id'], 'C-001')
        self.assertIn("'Atlantis'", warnings[0]['message'])

    def test_export_countries_all_invalid_omits_element(self):
        """When no value resolves, no ExportCountries element is emitted (rather
        than an empty or enum-invalid one) and the output still validates."""
        root = self._convert_validate_and_parse([self._make_xsd_valid_row(**{
            'Export Countries': 'Atlantis;Deutschland'})])
        self.assertIsNone(root.find('CounselingRecord/ClientIntake/ExportCountries'))
        warnings = self._export_country_warnings()
        self.assertEqual(len(warnings), 2)
        self.assertIn("'Deutschland'", warnings[1]['message'])

    def test_export_countries_case_insensitive_match(self):
        """A case-insensitive match is emitted with the enum's canonical casing."""
        root = self._convert_and_parse([self._make_valid_row(**{'Export Countries': 'united kingdom'})])
        codes = [e.text for e in root.findall('CounselingRecord/ClientIntake/ExportCountries/Code')]
        self.assertEqual(codes, ['United Kingdom'])
        self.assertEqual(self._export_country_warnings(), [])

    def test_issue_event_id_distinguishes_events_of_same_contact(self):
        """Two event rows for one contact hitting the same rule must be
        distinguishable by event_id (the motivating bug: the errors table
        showed only the shared Contact ID)."""
        rows = [
            self._make_valid_row(**{'Activity ID': 'A-100', 'Currently In Business?': 'Yes'}),
            self._make_valid_row(**{'Activity ID': 'A-200', 'Currently In Business?': 'Yes'}),
        ]
        self._convert_and_parse(rows)
        seeking = [i for i in self.validator.issues if i['field_name'] == 'CounselingSeeking']
        self.assertEqual(len(seeking), 2)
        self.assertEqual({i['record_id'] for i in seeking}, {'C-001'})
        self.assertEqual({i['event_id'] for i in seeking}, {'A-100', 'A-200'})

    def test_issue_event_id_empty_without_activity_id_column(self):
        """A CSV lacking the Activity ID column entirely yields empty event ids."""
        row = self._make_valid_row(**{'Currently In Business?': 'Yes'})
        del row['Activity ID']
        self._convert_and_parse([row])
        seeking = [i for i in self.validator.issues if i['field_name'] == 'CounselingSeeking']
        self.assertEqual(len(seeking), 1)
        self.assertEqual(seeking[0]['event_id'], '')

    def test_prevalidation_issue_inherits_event_id(self):
        """Missing Contact ID falls back to Row_N as record_id, but the event id
        still pinpoints the source row."""
        self._convert_and_parse([
            self._make_valid_row(**{'Contact ID': '', 'Activity ID': 'A-777'}),
            self._make_valid_row(),  # valid row so the file converts
        ])
        missing = [i for i in self.validator.issues if i['message'] == 'Missing required Contact ID.']
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['record_id'], 'Row_1')
        self.assertEqual(missing[0]['event_id'], 'A-777')

    def test_file_level_issue_has_empty_event_id(self):
        """File-level issues (record_id 'file') carry no event id."""
        from src.converters.base_converter import EmptyCSVError
        csv_path = self._write_csv([], fieldnames=['Contact ID', 'Activity ID'])
        xml_path = tempfile.NamedTemporaryFile(suffix='.xml', delete=False).name
        try:
            converter = CounselingConverter(self.logger, self.validator)
            with self.assertRaises(EmptyCSVError):
                converter.convert(csv_path, xml_path)
        finally:
            os.unlink(csv_path)
            if os.path.exists(xml_path):
                os.unlink(xml_path)
        file_issues = [i for i in self.validator.issues if i['record_id'] == 'file']
        self.assertEqual(len(file_issues), 1)
        self.assertEqual(file_issues[0]['event_id'], '')

    def test_counseling_output_unaffected_by_training_client_hooks(self):
        """The training-client subclass hooks must not change counseling output:
        PartnerSessionNumber still comes from Activity ID and no TrainingSession
        block is emitted."""
        root = self._convert_and_parse([self._make_valid_row(**{'Activity ID': 'A-123'})])
        counselor_record = root.find('CounselingRecord/CounselorRecord')
        self.assertEqual(counselor_record.find('PartnerSessionNumber').text, 'A-123')
        self.assertIsNone(counselor_record.find('TrainingSession'))


if __name__ == '__main__':
    unittest.main()
