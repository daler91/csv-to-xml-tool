import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import argparse
from datetime import datetime

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import the module to test
import src.fix_sba_xml as fix_sba_xml

class TestFixSBAXML(unittest.TestCase):

    def test_parse_arguments_file(self):
        """Test parsing arguments with --file."""
        test_args = ['fix_sba_xml.py', '--file', 'test.xml']
        with patch.object(sys, 'argv', test_args):
            args = fix_sba_xml.parse_arguments()
            self.assertEqual(args.file, 'test.xml')
            self.assertIsNone(args.directory)
            self.assertIsNone(args.output)
            self.assertFalse(args.no_backup)

    def test_parse_arguments_directory(self):
        """Test parsing arguments with --directory."""
        test_args = ['fix_sba_xml.py', '--directory', 'test_dir']
        with patch.object(sys, 'argv', test_args):
            args = fix_sba_xml.parse_arguments()
            self.assertEqual(args.directory, 'test_dir')
            self.assertIsNone(args.file)
            self.assertIsNone(args.output)
            self.assertFalse(args.recursive)
            self.assertEqual(args.pattern, '*.xml')

    def test_parse_arguments_mutually_exclusive(self):
        """Test that --file and --directory are mutually exclusive."""
        test_args = ['fix_sba_xml.py', '--file', 'test.xml', '--directory', 'test_dir']
        with patch.object(sys, 'argv', test_args):
            # argparse calls sys.exit(2) when parsing fails
            with self.assertRaises(SystemExit) as cm:
                # Mock stderr to suppress argparse error output in tests
                with patch('sys.stderr', new_callable=MagicMock):
                    fix_sba_xml.parse_arguments()
            self.assertEqual(cm.exception.code, 2)

    def test_parse_arguments_required(self):
        """Test that at least one of --file or --directory is required."""
        test_args = ['fix_sba_xml.py']
        with patch.object(sys, 'argv', test_args):
            with self.assertRaises(SystemExit) as cm:
                with patch('sys.stderr', new_callable=MagicMock):
                    fix_sba_xml.parse_arguments()
            self.assertEqual(cm.exception.code, 2)

    def test_parse_arguments_all_options(self):
        """Test parsing arguments with all options."""
        test_args = [
            'fix_sba_xml.py',
            '--directory', 'test_dir',
            '--output', 'out_dir',
            '--no-backup',
            '--recursive',
            '--pattern', '*.xmls',
            '--log-level', 'DEBUG',
            '--log-file'
        ]
        with patch.object(sys, 'argv', test_args):
            args = fix_sba_xml.parse_arguments()
            self.assertEqual(args.directory, 'test_dir')
            self.assertEqual(args.output, 'out_dir')
            self.assertTrue(args.no_backup)
            self.assertTrue(args.recursive)
            self.assertEqual(args.pattern, '*.xmls')
            self.assertEqual(args.log_level, 'DEBUG')
            self.assertTrue(args.log_file)

    @patch('src.fix_sba_xml.validator_fix_order')
    @patch('shutil.copy2')
    def test_process_single_file_success(self, mock_copy2, mock_validator_fix_order):
        """Test successful single file processing."""
        mock_validator_fix_order.return_value = True
        logger_mock = MagicMock()

        test_args = ['fix_sba_xml.py', '--file', 'test.xml']
        with patch.object(sys, 'argv', test_args):
            args = fix_sba_xml.parse_arguments()

            result = fix_sba_xml.process_single_file(args, logger_mock, mimic_original_add_missing=False)

            self.assertEqual(result, 0)
            mock_validator_fix_order.assert_called_once_with(
                xml_file='test.xml',
                output_file='test.xml',
                add_missing_elements_flag=False
            )
            mock_copy2.assert_called_once() # Backup should be created
            logger_mock.info.assert_any_call("[fix-sba-xml wrapper] Successfully fixed XML file: test.xml (via xml_validator)")

    @patch('src.fix_sba_xml.validator_fix_order')
    @patch('shutil.copy2')
    def test_process_single_file_failure(self, mock_copy2, mock_validator_fix_order):
        """Test failed single file processing."""
        mock_validator_fix_order.return_value = False
        logger_mock = MagicMock()

        test_args = ['fix_sba_xml.py', '--file', 'test.xml']
        with patch.object(sys, 'argv', test_args):
            args = fix_sba_xml.parse_arguments()

            result = fix_sba_xml.process_single_file(args, logger_mock, mimic_original_add_missing=False)

            self.assertEqual(result, 1)
            mock_validator_fix_order.assert_called_once()
            logger_mock.error.assert_called_with("[fix-sba-xml wrapper] Failed to fix XML file (via xml_validator)")

    @patch('src.fix_sba_xml.validator_fix_order')
    @patch('shutil.copy2')
    def test_process_single_file_no_backup(self, mock_copy2, mock_validator_fix_order):
        """Test that backup is not created when --no-backup is provided."""
        mock_validator_fix_order.return_value = True
        logger_mock = MagicMock()

        test_args = ['fix_sba_xml.py', '--file', 'test.xml', '--no-backup']
        with patch.object(sys, 'argv', test_args):
            args = fix_sba_xml.parse_arguments()

            fix_sba_xml.process_single_file(args, logger_mock, mimic_original_add_missing=False)

            mock_copy2.assert_not_called()

    @patch('src.fix_sba_xml.validator_fix_order')
    @patch('shutil.copy2')
    def test_process_single_file_different_output(self, mock_copy2, mock_validator_fix_order):
        """Test that backup is not created when output file is different."""
        mock_validator_fix_order.return_value = True
        logger_mock = MagicMock()

        test_args = ['fix_sba_xml.py', '--file', 'test.xml', '--output', 'out.xml']
        with patch.object(sys, 'argv', test_args):
            args = fix_sba_xml.parse_arguments()

            fix_sba_xml.process_single_file(args, logger_mock, mimic_original_add_missing=False)

            mock_copy2.assert_not_called()
            mock_validator_fix_order.assert_called_once_with(
                xml_file='test.xml',
                output_file='out.xml',
                add_missing_elements_flag=False
            )

    @patch('src.fix_sba_xml.validator_process_directory')
    def test_process_directory_success(self, mock_validator_process_directory):
        """Test successful directory processing."""
        mock_validator_process_directory.return_value = 5 # Mock 5 files processed
        logger_mock = MagicMock()

        test_args = ['fix_sba_xml.py', '--directory', 'test_dir', '--recursive', '--pattern', '*.xml']
        with patch.object(sys, 'argv', test_args):
            args = fix_sba_xml.parse_arguments()

            result = fix_sba_xml.process_directory(args, logger_mock, always_fix=True, mimic_original_add_missing=False)

            self.assertEqual(result, 0)
            mock_validator_process_directory.assert_called_once_with(
                input_dir='test_dir',
                output_dir=None,
                recursive=True,
                pattern='*.xml',
                xsd_file=None,
                fix=True,
                add_missing_elements_flag=False
            )
            logger_mock.info.assert_any_call("[fix-sba-xml wrapper] Successfully processed 5 XML files (via xml_validator)")

    @patch('src.fix_sba_xml.validator_process_directory')
    @patch('os.makedirs')
    @patch('os.path.exists')
    def test_process_directory_with_output(self, mock_exists, mock_makedirs, mock_validator_process_directory):
        """Test directory processing with output directory creation."""
        mock_validator_process_directory.return_value = 2
        mock_exists.return_value = False # Simulate output dir doesn't exist
        logger_mock = MagicMock()

        test_args = ['fix_sba_xml.py', '--directory', 'test_dir', '--output', 'out_dir']
        with patch.object(sys, 'argv', test_args):
            args = fix_sba_xml.parse_arguments()

            result = fix_sba_xml.process_directory(args, logger_mock, always_fix=True, mimic_original_add_missing=False)

            self.assertEqual(result, 0)
            mock_exists.assert_called_once_with('out_dir')
            mock_makedirs.assert_called_once_with('out_dir')
            mock_validator_process_directory.assert_called_once_with(
                input_dir='test_dir',
                output_dir='out_dir',
                recursive=False,
                pattern='*.xml',
                xsd_file=None,
                fix=True,
                add_missing_elements_flag=False
            )

    @patch('src.fix_sba_xml.validator_process_directory')
    @patch('os.makedirs')
    @patch('os.path.exists')
    def test_process_directory_with_output_side_effect(self, mock_exists, mock_makedirs, mock_validator_process_directory):
        """Test directory processing with output directory creation and side effects."""
        mock_validator_process_directory.return_value = 2
        # Patch exists to only return false for 'out_dir' to not break system calls
        def side_effect(path):
            if path == 'out_dir':
                return False
            return True
        mock_exists.side_effect = side_effect
        logger_mock = MagicMock()

        test_args = ['fix_sba_xml.py', '--directory', 'test_dir', '--output', 'out_dir']
        with patch.object(sys, 'argv', test_args):
            args = fix_sba_xml.parse_arguments()

            result = fix_sba_xml.process_directory(args, logger_mock, always_fix=True, mimic_original_add_missing=False)

            self.assertEqual(result, 0)
            mock_exists.assert_any_call('out_dir')
            mock_makedirs.assert_called_once_with('out_dir')
            mock_validator_process_directory.assert_called_once_with(
                input_dir='test_dir',
                output_dir='out_dir',
                recursive=False,
                pattern='*.xml',
                xsd_file=None,
                fix=True,
                add_missing_elements_flag=False
            )

    @patch('src.fix_sba_xml.process_single_file')
    @patch('src.fix_sba_xml.setup_logger')
    def test_main_file(self, mock_setup_logger, mock_process_single_file):
        """Test main entry point with --file."""
        mock_process_single_file.return_value = 0
        logger_mock = MagicMock()
        mock_setup_logger.return_value = logger_mock

        test_args = ['fix_sba_xml.py', '--file', 'test.xml']
        with patch.object(sys, 'argv', test_args):
            result = fix_sba_xml.main()

            self.assertEqual(result, 0)
            mock_process_single_file.assert_called_once()
            args, _ = mock_process_single_file.call_args[0][:2]
            self.assertEqual(args.file, 'test.xml')
            self.assertFalse(mock_process_single_file.call_args[0][2]) # mimic_original_add_missing

    @patch('src.fix_sba_xml.process_directory')
    @patch('src.fix_sba_xml.setup_logger')
    def test_main_directory(self, mock_setup_logger, mock_process_directory):
        """Test main entry point with --directory."""
        mock_process_directory.return_value = 0
        logger_mock = MagicMock()
        mock_setup_logger.return_value = logger_mock

        test_args = ['fix_sba_xml.py', '--directory', 'test_dir']
        with patch.object(sys, 'argv', test_args):
            result = fix_sba_xml.main()

            self.assertEqual(result, 0)
            mock_process_directory.assert_called_once()
            args, _ = mock_process_directory.call_args[0][:2]
            self.assertEqual(args.directory, 'test_dir')
            self.assertTrue(mock_process_directory.call_args[0][2]) # always_fix
            self.assertFalse(mock_process_directory.call_args[0][3]) # mimic_original_add_missing

    @patch('src.fix_sba_xml.process_single_file')
    @patch('src.fix_sba_xml.setup_logger')
    def test_main_exception(self, mock_setup_logger, mock_process_single_file):
        """Test main entry point handling exception."""
        mock_process_single_file.side_effect = OSError("Test Error")
        logger_mock = MagicMock()
        mock_setup_logger.return_value = logger_mock

        test_args = ['fix_sba_xml.py', '--file', 'test.xml']
        with patch.object(sys, 'argv', test_args):
            result = fix_sba_xml.main()

            self.assertEqual(result, 1)
            logger_mock.error.assert_called_once_with("[fix-sba-xml wrapper] Error: Test Error")

if __name__ == '__main__':
    unittest.main()
