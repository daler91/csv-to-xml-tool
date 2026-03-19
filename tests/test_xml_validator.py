import unittest
from unittest.mock import patch
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

# Import xml_validator module (renamed from xml-validator.py to xml_validator.py)
import xml_validator

class TestValidateAgainstXsd(unittest.TestCase):

    def test_validate_against_xsd_exception(self):
        # We can patch using getattr since the module has a dash
        with patch.object(xml_validator.etree, 'parse') as mock_parse:
            # Setup mock to raise an exception
            mock_parse.side_effect = Exception("Test exception")

            # Call the function
            is_valid, errors = xml_validator.validate_against_xsd("dummy.xml", "dummy.xsd")

            # Verify the exception was caught and returned correctly
            self.assertFalse(is_valid)
            self.assertEqual(errors, ["Validation error: Test exception"])

if __name__ == '__main__':
    unittest.main()
