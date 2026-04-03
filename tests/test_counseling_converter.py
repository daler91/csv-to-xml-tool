import unittest
import os
import sys
import tempfile
import csv
import xml.etree.ElementTree as ET

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.converters.counseling_converter import CounselingConverter
from src.logging_util import ConversionLogger
from src.validation_report import ValidationTracker

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


if __name__ == '__main__':
    unittest.main()
