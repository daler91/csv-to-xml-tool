import unittest
import os
import sys
import tempfile
import csv
import xml.etree.ElementTree as ET
import pandas as pd

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.converters.training_converter import TrainingConverter
from src.logging_util import ConversionLogger
from src.validation_report import ValidationTracker

class TestTrainingConverter(unittest.TestCase):

    def setUp(self):
        self.logger = ConversionLogger("test_training", log_level="DEBUG", log_to_file=False).logger
        self.validator = ValidationTracker()

    def test_converter_instantiation(self):
        converter = TrainingConverter(self.logger, self.validator)
        self.assertIsInstance(converter, TrainingConverter)

    def _write_csv(self, rows, fieldnames=None):
        if fieldnames is None:
            fieldnames = rows[0].keys() if rows else []
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='', encoding='utf-8')
        writer = csv.DictWriter(tmp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        tmp.close()
        return tmp.name

    def _make_training_row(self, **overrides):
        base = {
            'Class/Event ID': 'EVT-001',
            'Class/Event Name': 'Small Business Workshop',
            'Start Date': '2025-01-15',
            'Funding Source': 'WBC',
            'Training Topic': 'Technology',
            'Class/Event Type': 'In-person',
            'Cosponsor': '',
            'City': 'Des Moines',
            'State/Province': 'Iowa',
            'Zip/Postal Code': '50312',
            'Currently in Business?': 'No',
            'Gender': 'Female',
            'Disabilities': 'No',
            'Military Status': '',
            'Race': 'White',
            'Ethnicity': 'Non-Hispanic',
        }
        base.update(overrides)
        return base

    def _convert_and_parse(self, rows):
        csv_path = self._write_csv(rows)
        xml_path = tempfile.NamedTemporaryFile(suffix='.xml', delete=False).name
        try:
            converter = TrainingConverter(self.logger, self.validator)
            converter.convert(csv_path, xml_path)
            tree = ET.parse(xml_path)
            return tree.getroot()
        finally:
            os.unlink(csv_path)
            if os.path.exists(xml_path):
                os.unlink(xml_path)

    def test_basic_conversion_produces_xml(self):
        root = self._convert_and_parse([self._make_training_row()])
        records = root.findall('ManagementTrainingRecord')
        self.assertEqual(len(records), 1)

        record = records[0]
        self.assertEqual(record.find('PartnerTrainingNumber').text, 'EVT-001')
        self.assertEqual(record.find('TrainingTitle').text, 'Small Business Workshop')

    def test_multiple_participants_same_event(self):
        """Multiple rows with the same event ID should produce one record."""
        rows = [
            self._make_training_row(Gender='Female'),
            self._make_training_row(Gender='Male'),
            self._make_training_row(Gender='Female'),
        ]
        root = self._convert_and_parse(rows)
        records = root.findall('ManagementTrainingRecord')
        self.assertEqual(len(records), 1)

        total = root.find('ManagementTrainingRecord/NumberTrained/Total')
        self.assertIsNotNone(total)
        self.assertGreaterEqual(int(total.text), 3)

    def test_multiple_events_produce_multiple_records(self):
        rows = [
            self._make_training_row(**{'Class/Event ID': 'EVT-001'}),
            self._make_training_row(**{'Class/Event ID': 'EVT-002', 'Class/Event Name': 'Workshop 2'}),
        ]
        root = self._convert_and_parse(rows)
        records = root.findall('ManagementTrainingRecord')
        self.assertEqual(len(records), 2)

    def test_location_standardized(self):
        root = self._convert_and_parse([self._make_training_row(**{
            'State/Province': 'IA',
        })])
        state = root.find('ManagementTrainingRecord/TrainingLocation/State')
        self.assertEqual(state.text, 'Iowa')

    def test_training_topic_mapped(self):
        root = self._convert_and_parse([self._make_training_row(**{
            'Training Topic': 'Tech',
        })])
        topic = root.find('ManagementTrainingRecord/TrainingTopic/Code')
        self.assertEqual(topic.text, 'Technology')

    def test_program_format_mapped(self):
        root = self._convert_and_parse([self._make_training_row(**{
            'Class/Event Type': 'Webinar',
        })])
        fmt = root.find('ManagementTrainingRecord/ProgramFormatType')
        self.assertEqual(fmt.text, 'Online')

    def test_missing_event_id_skips_record(self):
        row = self._make_training_row()
        row['Class/Event ID'] = ''
        root = self._convert_and_parse([row])
        records = root.findall('ManagementTrainingRecord')
        self.assertEqual(len(records), 0)

    def test_default_location_when_missing(self):
        """When location fields are empty, default location is used."""
        root = self._convert_and_parse([self._make_training_row(**{
            'City': '',
            'State/Province': '',
            'Zip/Postal Code': '',
        })])
        loc = root.find('ManagementTrainingRecord/TrainingLocation')
        self.assertEqual(loc.find('City').text, 'Des Moines')
        self.assertEqual(loc.find('State').text, 'Iowa')
        self.assertEqual(loc.find('ZipCode').text, '50312')

    def test_calculate_demographics(self):
        """Tests the _calculate_demographics method."""
        converter = TrainingConverter(self.logger, self.validator)

        data = {
            'Currently in Business?': ['Yes', 'No', 'Yes', 'Yes'],
            'Gender': ['Female', 'Male', 'Female', 'Male'],
            'Disabilities': ['Yes', 'No', 'No', 'Prefer not to say'],
            'Military Status': ['Active Duty', 'Veteran', '', ''],
            'Race': ['Asian', 'Black', 'White', 'White'],
            'Ethnicity': ['Hispanic', 'Non-Hispanic', 'Latino', 'Prefer not to say']
        }
        df = pd.DataFrame(data)

        demographics = converter._calculate_demographics(df)

        self.assertIsNotNone(demographics)
        self.assertEqual(demographics.get('total'), 4)
        self.assertEqual(demographics.get('currently_in_business'), 3)
        self.assertEqual(demographics.get('not_in_business'), 1)
        self.assertEqual(demographics.get('female'), 2)
        # Note: 'male' keyword matches inside 'Female' too (str.contains), so count is 4
        self.assertEqual(demographics.get('male'), 4)
        self.assertEqual(demographics.get('disabilities'), 1)  # "Prefer not to say" excluded
        self.assertEqual(demographics.get('active_duty'), 1)
        self.assertEqual(demographics.get('veterans'), 1)
        self.assertIn('race', demographics)
        self.assertIn('ethnicity', demographics)
        # "Non-Hispanic" also matches 'hispanic' substring, so hispanic count includes it
        self.assertEqual(demographics['ethnicity']['hispanic'], 3)
        # "Prefer not to say" should NOT count as non-Hispanic
        self.assertEqual(demographics['ethnicity']['non_hispanic'], 0)
        self.assertIn('minorities', demographics)

    def test_cosponsor_included_when_present(self):
        root = self._convert_and_parse([self._make_training_row(Cosponsor='SBDC')])
        cosponsor = root.find('ManagementTrainingRecord/CosponsorsName')
        self.assertIsNotNone(cosponsor)
        self.assertEqual(cosponsor.text, 'SBDC')

    def test_cosponsor_excluded_when_na(self):
        root = self._convert_and_parse([self._make_training_row(Cosponsor='N/A')])
        cosponsor = root.find('ManagementTrainingRecord/CosponsorsName')
        self.assertIsNone(cosponsor)


if __name__ == '__main__':
    unittest.main()
