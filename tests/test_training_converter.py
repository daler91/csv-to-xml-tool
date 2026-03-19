import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.converters.training_converter import TrainingConverter
from src.logging_util import ConversionLogger
from src.validation_report import ValidationTracker
from src.config import ValidationCategory
import tempfile

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

    @patch('src.converters.training_converter.TrainingConverter._build_location_section')
    def test_convert_unhandled_exception(self, mock_build_location):
        """
        Tests that an unhandled exception during event processing is caught, logged,
        and added to the validation tracker, and the conversion continues.
        """
        import pandas as pd

        mock_logger = MagicMock()
        mock_validator = MagicMock()
        converter = TrainingConverter(mock_logger, mock_validator)

        # Configure the mock to raise an exception when _build_location_section is called
        test_exception = Exception("Test unhandled exception")
        mock_build_location.side_effect = test_exception

        # Create a temporary CSV file with valid data
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Class/Event ID,Start Date,Event Name\n")
            f.write("EVENT-123,2023-12-12,Test Event\n")
            input_path = f.name

        output_path = input_path.replace('.csv', '.xml')

        try:
            # Run the conversion
            converter.convert(input_path, output_path)

            # Verify the exception was caught and logged correctly
            mock_logger.error.assert_called_with("Error processing event EVENT-123: Test unhandled exception", exc_info=True)

            # Verify the validation tracker recorded the error and processing failure
            mock_validator.add_issue.assert_called_with(
                "EVENT-123",
                "error",
                ValidationCategory.PROCESSING_ERROR,
                "record",
                "Unhandled error: Test unhandled exception"
            )
            mock_validator.record_processed.assert_called_with(success=False)

        finally:
            # Clean up temporary files
            if os.path.exists(input_path):
                os.remove(input_path)
            if os.path.exists(output_path):
                os.remove(output_path)

if __name__ == '__main__':
    unittest.main()
