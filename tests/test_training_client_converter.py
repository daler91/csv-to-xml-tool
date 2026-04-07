import unittest
import os
import sys
import tempfile
import csv
import xml.etree.ElementTree as ET

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.converters.training_client_converter import TrainingClientConverter
from src.logging_util import ConversionLogger
from src.validation_report import ValidationTracker


class TestTrainingClientConverter(unittest.TestCase):

    def setUp(self):
        self.logger = ConversionLogger("test_training_client", log_level="DEBUG", log_to_file=False).logger
        self.validator = ValidationTracker()

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
        """Return a minimal valid training client row dict with optional overrides."""
        base = {
            'Class/Event ID': '701Pe00000vtCVy',
            'Member Type': 'Contact',
            'First Name': 'Jane',
            'Last Name': 'Doe',
            'Member Status': 'Responded',
            'Company': 'Doe Enterprises',
            'Phone': '5155551234',
            'Email': 'jane@example.com',
            'Unique Campaign Members': '1',
            'Currently in Business?': 'No',
            'Ethnicity': 'Non Hispanic or Latino',
            'Race': 'White',
            'Disabilities': 'No',
            'Gender': 'Female',
            'Military Status': 'No military service',
            'Related Record ID': '003Pe00000Sxsp4',
            'Training Topic': '',
            'Class/Event Type': 'Online',
            'Funding Source': '',
            'Member ID': '00vPe00000Pn89L',
            'Class Teacher': 'Mike Smith',
            'Contact ID': '003Pe00000Sxsp4',
            'Street': '2210 Grand Ave',
            'city': 'Des Moines',
            'State': 'IA',
            'Zip code': '50312',
            'Start Date': '1/15/2026',
            'Class/Event Name': 'Small Business Taxes: Getting Ready for Tax Time',
        }
        base.update(overrides)
        return base

    def _convert_and_parse(self, rows):
        """Convert rows to XML and return parsed root element."""
        csv_path = self._write_csv(rows)
        xml_path = tempfile.NamedTemporaryFile(suffix='.xml', delete=False).name
        try:
            converter = TrainingClientConverter(self.logger, self.validator)
            converter.convert(csv_path, xml_path)
            tree = ET.parse(xml_path)
            return tree.getroot()
        finally:
            os.unlink(csv_path)
            if os.path.exists(xml_path):
                os.unlink(xml_path)

    def test_basic_conversion_produces_valid_xml(self):
        """Test that a valid training client row produces a CounselingRecord element."""
        root = self._convert_and_parse([self._make_valid_row()])
        records = root.findall('CounselingRecord')
        self.assertEqual(len(records), 1)

        record = records[0]
        self.assertEqual(record.find('PartnerClientNumber').text, '003Pe00000Sxsp4')
        self.assertEqual(record.find('Location/LocationCode').text, '249003')

    def test_column_remapping_address(self):
        """Test that training client address columns map to XML address fields."""
        root = self._convert_and_parse([self._make_valid_row()])
        addr = root.find('CounselingRecord/ClientRequest/AddressPart1')
        self.assertEqual(addr.find('Street1').text, '2210 Grand Ave')
        self.assertEqual(addr.find('City').text, 'Des Moines')
        self.assertEqual(addr.find('State').text, 'Iowa')
        self.assertEqual(addr.find('ZipCode').text, '50312')
        self.assertEqual(addr.find('Country/Code').text, 'United States')

    def test_column_remapping_phone(self):
        """Test that Phone column maps to PhonePart1/Primary."""
        root = self._convert_and_parse([self._make_valid_row(Phone='5155551234')])
        phone = root.find('CounselingRecord/ClientRequest/PhonePart1/Primary')
        self.assertIsNotNone(phone)
        self.assertEqual(phone.text, '5155551234')

    def test_column_remapping_company(self):
        """Test that Company column maps to CompanyName."""
        root = self._convert_and_parse([self._make_valid_row(Company='Test Corp')])
        company = root.find('CounselingRecord/ClientIntake/CompanyName')
        self.assertEqual(company.text, 'Test Corp')

    def test_column_remapping_session_id(self):
        """Test that Class/Event ID maps to PartnerSessionNumber."""
        root = self._convert_and_parse([self._make_valid_row(**{'Class/Event ID': 'EVT-123'})])
        session_num = root.find('CounselingRecord/CounselorRecord/PartnerSessionNumber')
        self.assertEqual(session_num.text, 'EVT-123')

    def test_column_remapping_counselor_name(self):
        """Test that Class Teacher maps to CounselorName."""
        root = self._convert_and_parse([self._make_valid_row(**{'Class Teacher': 'Mike Smith'})])
        counselor = root.find('CounselingRecord/CounselorRecord/CounselorName')
        self.assertEqual(counselor.text, 'Mike Smith')

    def test_column_remapping_date_counseled(self):
        """Test that Start Date maps to DateCounseled."""
        root = self._convert_and_parse([self._make_valid_row(**{'Start Date': '1/15/2026'})])
        date = root.find('CounselingRecord/CounselorRecord/DateCounseled')
        self.assertEqual(date.text, '2026-01-15')

    def test_column_remapping_session_type(self):
        """Test that Class/Event Type maps to SessionType."""
        root = self._convert_and_parse([self._make_valid_row(**{'Class/Event Type': 'Online'})])
        session_type = root.find('CounselingRecord/CounselorRecord/SessionType')
        self.assertEqual(session_type.text, 'Online')

    def test_passthrough_columns(self):
        """Test that columns matching counseling format pass through unchanged."""
        root = self._convert_and_parse([self._make_valid_row()])
        cr = root.find('CounselingRecord/ClientRequest')
        self.assertEqual(cr.find('ClientNamePart1/First').text, 'Jane')
        self.assertEqual(cr.find('ClientNamePart1/Last').text, 'Doe')
        self.assertEqual(cr.find('Email').text, 'jane@example.com')

    def test_demographics_mapped(self):
        """Test that demographic fields are correctly mapped."""
        root = self._convert_and_parse([self._make_valid_row(
            Gender='Female',
            Race='White',
            Ethnicity='Non Hispanic or Latino',
        )])
        intake = root.find('CounselingRecord/ClientIntake')
        self.assertEqual(intake.find('Sex').text, 'Female')
        self.assertEqual(intake.find('Race/Code').text, 'White')
        self.assertEqual(intake.find('Ethnicity').text, 'Non Hispanic or Latino')

    def test_currently_in_business_remapped(self):
        """Test that 'Currently in Business?' (lowercase) maps correctly."""
        root = self._convert_and_parse([self._make_valid_row(**{'Currently in Business?': 'Yes'})])
        cib = root.find('CounselingRecord/ClientIntake/CurrentlyInBusiness')
        self.assertEqual(cib.text, 'Yes')

    def test_defaults_applied_financial(self):
        """Test that financial fields default to 0."""
        root = self._convert_and_parse([self._make_valid_row()])
        income = root.find('CounselingRecord/CounselorRecord/ClientAnnualIncomePart3')
        self.assertEqual(income.find('GrossRevenues').text, '0')
        self.assertEqual(income.find('ProfitLoss').text, '0')

        rpsc = root.find('CounselingRecord/CounselorRecord/ResourcePartnerServiceContributed')
        self.assertEqual(rpsc.find('SBALoanAmount').text, '0')

    def test_defaults_applied_language(self):
        """Test that language defaults to English."""
        root = self._convert_and_parse([self._make_valid_row()])
        lang = root.find('CounselingRecord/CounselorRecord/Language/Code')
        self.assertEqual(lang.text, 'English')

    def test_defaults_applied_counseling_provided(self):
        """Test that counseling provided defaults to Business Start-up/Preplanning."""
        root = self._convert_and_parse([self._make_valid_row()])
        cp = root.find('CounselingRecord/CounselorRecord/CounselingProvided/Code')
        self.assertEqual(cp.text, 'Business Start-up/Preplanning')

    def test_missing_contact_id_skips_record(self):
        """Records without Contact ID should be skipped."""
        row = self._make_valid_row(**{'Contact ID': ''})
        root = self._convert_and_parse([row])
        records = root.findall('CounselingRecord')
        self.assertEqual(len(records), 0)

    def test_multiple_records_converted(self):
        """Test that multiple training client rows produce multiple records."""
        rows = [
            self._make_valid_row(**{'Contact ID': 'C-001', 'First Name': 'Melissa'}),
            self._make_valid_row(**{'Contact ID': 'C-002', 'First Name': 'Robin'}),
        ]
        root = self._convert_and_parse(rows)
        records = root.findall('CounselingRecord')
        self.assertEqual(len(records), 2)

    def test_training_only_columns_ignored(self):
        """Training-only columns should not cause errors or appear in XML."""
        row = self._make_valid_row(**{
            'Training Topic': 'Technology',
            'Member Type': 'Contact',
            'Class/Event Name': 'Business Basics Workshop',
        })
        root = self._convert_and_parse([row])
        records = root.findall('CounselingRecord')
        self.assertEqual(len(records), 1)

    def test_military_status_mapped(self):
        """Test that Military Status maps to MilitaryStatus via Veteran Status."""
        root = self._convert_and_parse([self._make_valid_row(**{'Military Status': 'Veteran'})])
        ms = root.find('CounselingRecord/ClientIntake/MilitaryStatus')
        self.assertEqual(ms.text, 'Veteran')

    def test_disability_mapped(self):
        """Test that Disabilities column maps to Disability."""
        root = self._convert_and_parse([self._make_valid_row(Disabilities='Yes')])
        disability = root.find('CounselingRecord/ClientIntake/Disability')
        self.assertEqual(disability.text, 'Yes')

    def test_race_with_semicolons(self):
        """Test that race values with semicolons are split correctly."""
        root = self._convert_and_parse([self._make_valid_row(Race='White; ')])
        race_codes = root.findall('CounselingRecord/ClientIntake/Race/Code')
        self.assertTrue(len(race_codes) >= 1)
        self.assertEqual(race_codes[0].text, 'White')


if __name__ == '__main__':
    unittest.main()
