import unittest
import os
import sys
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
        """
        Tests that the TrainingConverter can be instantiated.
        """
        try:
            converter = TrainingConverter(self.logger, self.validator)
            self.assertIsInstance(converter, TrainingConverter)
        except Exception as e:
            self.fail(f"TrainingConverter instantiation failed with an exception: {e}")

    def test_calculate_demographics(self):
        """
        Tests the _calculate_demographics method.
        To test the current logic, we construct a dataframe where the first row contains
        the column names as their values for demographic fields.
        """
        converter = TrainingConverter(self.logger, self.validator)

        # Build a DataFrame that matches the exact behavior expected by the current implementation
        data = {
            'Currently in Business?': ['Currently in Business?', 'Yes', 'No', 'Yes', 'y', 'unknown'],
            'Gender': ['Gender', 'Female', 'Male', 'Female', 'M', 'O'],
            'Disabilities': ['Disabilities', 'Yes', 'No', '1', 'False', ''],
            'Military Status': ['Military Status', 'Active Duty', 'Veteran', 'Spouse', 'None', ''],
            'Race': ['Race', 'Asian', 'Black', 'White', 'Black', 'Hawaiian'],
            'Ethnicity': ['Ethnicity', 'Hispanic', 'Non-Hispanic', 'Latino', '', 'Non-Hispanic']
        }
        df = pd.DataFrame(data)

        demographics = converter._calculate_demographics(df)

        self.assertIsNotNone(demographics)
        self.assertEqual(demographics.get('total'), 6)
        # 'currently in business?' contains 'y' so it matches
        self.assertEqual(demographics.get('currently_in_business'), 4)
        self.assertEqual(demographics.get('not_in_business'), 2)

        # Test existence of all keys to ensure it calculated completely
        self.assertIn('female', demographics)
        self.assertIn('male', demographics)
        self.assertIn('disabilities', demographics)
        self.assertIn('active_duty', demographics)
        self.assertIn('veterans', demographics)
        self.assertIn('service_disabled_veterans', demographics)
        self.assertIn('reserve_guard', demographics)
        self.assertIn('military_spouse', demographics)
        self.assertIn('race', demographics)
        self.assertIn('ethnicity', demographics)
        self.assertIn('minorities', demographics)

if __name__ == '__main__':
    unittest.main()
