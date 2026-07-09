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

    def test_partner_session_number_uses_member_id(self):
        """PartnerSessionNumber is the per-attendee Member ID, not the shared event id."""
        root = self._convert_and_parse([self._make_valid_row()])
        session_num = root.find('CounselingRecord/CounselorRecord/PartnerSessionNumber')
        self.assertEqual(session_num.text, '00vPe00000Pn89L')

    def test_partner_session_number_falls_back_to_event_id(self):
        """Without a Member ID, PartnerSessionNumber falls back to the Class/Event ID."""
        root = self._convert_and_parse([self._make_valid_row(**{'Member ID': ''})])
        session_num = root.find('CounselingRecord/CounselorRecord/PartnerSessionNumber')
        self.assertEqual(session_num.text, '701Pe00000vtCVy')

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

    def test_session_type_forced_to_training(self):
        """Every training-member record is a Training session regardless of the
        Class/Event Type delivery format, with no invalid-value warning."""
        root = self._convert_and_parse([self._make_valid_row(**{'Class/Event Type': 'Online'})])
        session_type = root.find('CounselingRecord/CounselorRecord/SessionType')
        self.assertEqual(session_type.text, 'Training')
        session_type_issues = [i for i in self.validator.issues if i['field_name'] == 'SessionType']
        self.assertEqual(session_type_issues, [])

    def test_contact_hours_not_bumped_for_training(self):
        """Training sessions don't require contact hours, so all hours stay 0."""
        root = self._convert_and_parse([self._make_valid_row()])
        hours = root.find('CounselingRecord/CounselorRecord/CounselingHours')
        self.assertEqual(hours.find('Contact').text, '0')
        self.assertEqual(hours.find('Prepare').text, '0')
        self.assertEqual(hours.find('Travel').text, '0')

    def test_training_session_block(self):
        """The TrainingSession block is emitted as the last CounselorRecord child,
        carrying the start date, the event id, and the fixed attendee/hours values."""
        root = self._convert_and_parse([self._make_valid_row()])
        counselor_record = root.find('CounselingRecord/CounselorRecord')
        self.assertEqual(list(counselor_record)[-1].tag, 'TrainingSession')
        ts = counselor_record.find('TrainingSession')
        self.assertEqual(ts.find('DateTrainingStarted').text, '2026-01-15')
        self.assertEqual(ts.find('PartnerTrainingNumber').text, '701Pe00000vtCVy')
        self.assertEqual(ts.find('EmployeesTrained').text, '1')
        self.assertEqual(ts.find('HoursTrained').text, '1.5')
        self.assertEqual(
            [child.tag for child in ts],
            ['DateTrainingStarted', 'PartnerTrainingNumber', 'EmployeesTrained', 'HoursTrained'])

    def test_training_session_omits_blank_date_and_event_id(self):
        """Blank Start Date / Class/Event ID are omitted from TrainingSession
        rather than emitted empty (both are xs:date/String20 optional elements)."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Class/Event ID': '',
            'Start Date': '',
        })])
        ts = root.find('CounselingRecord/CounselorRecord/TrainingSession')
        self.assertIsNone(ts.find('DateTrainingStarted'))
        self.assertIsNone(ts.find('PartnerTrainingNumber'))
        self.assertEqual(ts.find('EmployeesTrained').text, '1')
        self.assertEqual(ts.find('HoursTrained').text, '1.5')

    def test_training_topic_maps_to_seeking_and_provided(self):
        """The event's Training Topic is recorded as the counseling sought and provided."""
        root = self._convert_and_parse([self._make_valid_row(**{'Training Topic': 'Buy/Sell Business'})])
        seeking = root.find('CounselingRecord/ClientIntake/CounselingSeeking/Code')
        provided = root.find('CounselingRecord/CounselorRecord/CounselingProvided/Code')
        self.assertEqual(seeking.text, 'Buy/Sell Business')
        self.assertEqual(provided.text, 'Buy/Sell Business')

    def test_blank_training_topic_keeps_defaults(self):
        """Blank topic: CounselingSeeking omitted, CounselingProvided keeps its default."""
        root = self._convert_and_parse([self._make_valid_row()])
        self.assertIsNone(root.find('CounselingRecord/ClientIntake/CounselingSeeking'))
        provided = root.find('CounselingRecord/CounselorRecord/CounselingProvided/Code')
        self.assertEqual(provided.text, 'Business Start-up/Preplanning')

    def test_explicit_counseling_columns_beat_training_topic(self):
        """A counseling-format column in the raw CSV wins over the Training Topic."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Training Topic': 'Marketing',
            'Nature of the Counseling Seeking?': 'Business Plan',
        })])
        seeking = root.find('CounselingRecord/ClientIntake/CounselingSeeking/Code')
        self.assertEqual(seeking.text, 'Business Plan')

    def test_training_topic_counts_as_counseling_seeking_for_in_business(self):
        """A topic satisfies the counseling-seeking half of the in-business details,
        so 'Yes' with a legal entity and a topic is not downgraded."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Currently in Business?': 'Yes',
            'Legal Entity of Business': 'LLC',
            'Training Topic': 'Marketing',
        })])
        cib = root.find('CounselingRecord/ClientIntake/CurrentlyInBusiness')
        self.assertEqual(cib.text, 'Yes')
        downgraded = [i for i in self.validator.issues if i['category'] == 'downgraded_value']
        self.assertEqual(downgraded, [])

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
        """'Currently in Business?' (lowercase) maps correctly, and 'Yes' survives
        when the CSV passes through the required business-detail columns."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Currently in Business?': 'Yes',
            'Legal Entity of Business': 'LLC',
            'Nature of the Counseling Seeking?': 'Business Start-up/Preplanning',
        })])
        intake = root.find('CounselingRecord/ClientIntake')
        self.assertEqual(intake.find('CurrentlyInBusiness').text, 'Yes')
        self.assertEqual(intake.find('LegalEntity/Code').text, 'LLC')
        self.assertIsNotNone(intake.find('CounselingSeeking'))
        downgraded = [i for i in self.validator.issues if i['category'] == 'downgraded_value']
        self.assertEqual(downgraded, [])

    def test_in_business_without_details_downgraded_to_no(self):
        """A 'Yes' row without business details is recorded as not in business:
        one downgrade warning, no LegalEntity element, and no errors."""
        root = self._convert_and_parse([self._make_valid_row(**{'Currently in Business?': 'Yes'})])
        intake = root.find('CounselingRecord/ClientIntake')
        self.assertEqual(intake.find('CurrentlyInBusiness').text, 'No')
        self.assertIsNone(intake.find('LegalEntity'))
        errors = [i for i in self.validator.issues if i['severity'] == 'error']
        self.assertEqual(errors, [])
        downgraded = [i for i in self.validator.issues if i['category'] == 'downgraded_value']
        self.assertEqual(len(downgraded), 1)
        self.assertEqual(downgraded[0]['field_name'], 'CurrentlyInBusiness')

    def test_in_business_with_partial_details_still_downgraded(self):
        """Legal entity alone isn't enough — counseling seeking is also required
        for an in-business client, so the row is still downgraded."""
        root = self._convert_and_parse([self._make_valid_row(**{
            'Currently in Business?': 'Yes',
            'Legal Entity of Business': 'LLC',
        })])
        cib = root.find('CounselingRecord/ClientIntake/CurrentlyInBusiness')
        self.assertEqual(cib.text, 'No')
        downgraded = [i for i in self.validator.issues if i['category'] == 'downgraded_value']
        self.assertEqual(len(downgraded), 1)

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

    def test_injected_defaults_do_not_warn_fabricated_default(self):
        """The counseling defaults injected by TrainingClientConfig.DEFAULTS for
        columns absent from the shorter training-client form (blank revenue fields
        defaulted to '0', Mailing Country 'US', etc.) are intentional and must not
        produce a per-row FABRICATED_DEFAULT warning storm."""
        rows = [
            self._make_valid_row(**{'Contact ID': 'C-001'}),
            self._make_valid_row(**{'Contact ID': 'C-002', 'First Name': 'Robin'}),
        ]
        self._convert_and_parse(rows)
        fabricated = [i for i in self.validator.issues if i['category'] == 'fabricated_default']
        self.assertEqual(fabricated, [])

    def test_issue_event_id_from_class_event_id(self):
        """Issues carry the Class/Event ID as event_id — proves the
        remap-to-Activity-ID happens before the per-row context is set."""
        self._convert_and_parse([self._make_valid_row(**{
            'Class/Event ID': 'EVT-9',
            'Currently in Business?': 'Yes',
        })])
        downgraded = [i for i in self.validator.issues if i['field_name'] == 'CurrentlyInBusiness']
        self.assertEqual(len(downgraded), 1)
        self.assertEqual(downgraded[0]['severity'], 'warning')
        self.assertEqual(downgraded[0]['record_id'], '003Pe00000Sxsp4')
        self.assertEqual(downgraded[0]['event_id'], 'EVT-9')


if __name__ == '__main__':
    unittest.main()
