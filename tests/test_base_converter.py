import unittest
import os
import sys

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.converters.base_converter import BaseConverter
from src.logging_util import ConversionLogger
from src.validation_report import ValidationTracker

class TestBaseConverter(unittest.TestCase):

    def setUp(self):
        self.logger = ConversionLogger("test_base", log_level="DEBUG", log_to_file=False).logger
        self.validator = ValidationTracker()

    def test_cannot_instantiate_abc(self):
        """
        Tests that BaseConverter cannot be instantiated directly because it's an ABC.
        """
        with self.assertRaisesRegex(TypeError, "Can't instantiate abstract class BaseConverter"):
            BaseConverter(self.logger, self.validator)

    def test_subclass_must_implement_convert(self):
        """
        Tests that a subclass must implement the 'convert' method.
        """
        class IncompleteConverter(BaseConverter):
            pass

        with self.assertRaisesRegex(TypeError, "Can't instantiate abstract class IncompleteConverter"):
            IncompleteConverter(self.logger, self.validator)

    def test_subclass_with_convert_can_be_instantiated(self):
        """
        Tests that a subclass that implements 'convert' can be instantiated.
        """
        class CompleteConverter(BaseConverter):
            def convert(self, input_path: str, output_path: str):
                pass

        converter = CompleteConverter(self.logger, self.validator)
        self.assertIsInstance(converter, CompleteConverter)
        self.assertIsInstance(converter, BaseConverter)
        self.assertEqual(converter.logger, self.logger)
        self.assertEqual(converter.validator, self.validator)

if __name__ == '__main__':
    unittest.main()
