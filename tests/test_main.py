import unittest
import os
import sys
from unittest.mock import patch, MagicMock

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.main import main

class TestMain(unittest.TestCase):
    def setUp(self):
        # Prevent argparse from actually exiting the test suite on error
        self.exit_patcher = patch('sys.exit')
        self.mock_exit = self.exit_patcher.start()

    def tearDown(self):
        self.exit_patcher.stop()

    @patch('src.main.os.path.exists')
    @patch('src.main.os.makedirs')
    @patch('src.main.ValidationTracker')
    @patch('src.main.ConversionLogger')
    def test_happy_path(self, mock_logger, mock_validator, mock_makedirs, mock_exists):
        """Test successful execution with input and output files."""
        # Setup mocks
        mock_exists.return_value = True
        mock_converter_instance = MagicMock()

        # Patch the dict lookup directly rather than using mock_converters
        with patch.dict('src.main.CONVERTERS', {'counseling': MagicMock(return_value=mock_converter_instance)}):
            # Avoid file logging trying to write to real directories during test
            mock_logger.return_value.logger = MagicMock()

            test_args = ['main.py', 'convert', 'counseling', '--input', 'test.csv', '--output', 'test.xml', '--log-dir', 'test_logs', '--report-dir', 'test_reports']
            with patch.object(sys, 'argv', test_args):
                # Patch os.path.exists to only return true for the input file, not for everything
                def side_effect(path):
                    if path == 'test.csv':
                        return True
                    return False
                mock_exists.side_effect = side_effect

                main()

            # Assertions
            mock_converter_instance.convert.assert_called_with('test.csv', 'test.xml')
            self.mock_exit.assert_not_called()

    @patch('src.main.ConversionLogger')
    @patch('src.main.os.path.exists')
    @patch('src.main.os.makedirs')
    def test_missing_input_file(self, mock_makedirs, mock_exists, mock_logger):
        """Test execution when input file is missing."""
        # os.path.exists checking for file and log directories
        def side_effect(path):
            if path == 'missing.csv':
                return False
            return True
        mock_exists.side_effect = side_effect

        mock_logger_instance = MagicMock()
        mock_logger.return_value.logger = mock_logger_instance

        with patch.dict('src.main.CONVERTERS', {'training': MagicMock()}):
            test_args = ['main.py', 'convert', 'training', '--input', 'missing.csv', '--log-dir', 'test_logs', '--report-dir', 'test_reports']
            with patch.object(sys, 'argv', test_args):
                main()

            # Assertions
            mock_exists.assert_any_call('missing.csv')
            mock_logger_instance.error.assert_called_with('Input file not found: missing.csv')
            self.mock_exit.assert_called_with(1)

    @patch('src.main.os.path.exists')
    @patch('src.main.os.makedirs')
    @patch('src.main.datetime')
    @patch('src.main.ConversionLogger')
    @patch('src.main.ValidationTracker')
    def test_output_path_fallback(self, mock_validator, mock_logger, mock_datetime, mock_makedirs, mock_exists):
        """Test fallback output path generation when --output is not provided."""
        mock_exists.return_value = True
        mock_datetime.now.return_value.strftime.return_value = '20230101_120000'
        mock_converter_instance = MagicMock()
        mock_logger.return_value.logger = MagicMock()

        with patch.dict('src.main.CONVERTERS', {'counseling': MagicMock(return_value=mock_converter_instance)}):
            test_args = ['main.py', 'convert', 'counseling', '--input', 'dir/test.csv', '--log-dir', 'test_logs', '--report-dir', 'test_reports']
            with patch.object(sys, 'argv', test_args):
                main()

            # Assertions
            expected_output_path = os.path.join('dir', 'test_20230101_120000.xml')
            mock_converter_instance.convert.assert_called_with('dir/test.csv', expected_output_path)
            self.mock_exit.assert_not_called()

    @patch('src.main.os.path.exists')
    @patch('src.main.os.makedirs')
    @patch('src.main.ConversionLogger')
    def test_exception_handling(self, mock_logger, mock_makedirs, mock_exists):
        """Test that exceptions during conversion are caught and logged."""
        mock_exists.return_value = True
        mock_logger_instance = MagicMock()
        mock_logger.return_value.logger = mock_logger_instance

        # Make the converter raise an exception
        mock_converter_class = MagicMock()
        mock_converter_class.side_effect = Exception("Test exception")

        with patch.dict('src.main.CONVERTERS', {'training': mock_converter_class}):
            test_args = ['main.py', 'convert', 'training', '--input', 'test.csv', '--log-dir', 'test_logs', '--report-dir', 'test_reports']
            with patch.object(sys, 'argv', test_args):
                main()

            # Assertions
            mock_logger_instance.error.assert_called_once()
            args, kwargs = mock_logger_instance.error.call_args
            self.assertIn("An unexpected error occurred: Test exception", args[0])
            self.assertTrue(kwargs.get('exc_info'))
            self.mock_exit.assert_called_with(1)

if __name__ == '__main__':
    unittest.main()
