import unittest
from unittest.mock import patch
import sys
import os
import tempfile
import shutil

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

# Import xml_validator module
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


class TestProcessDirectory(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for testing
        self.test_dir = tempfile.mkdtemp()

        # Create some dummy XML files
        self.file1_path = os.path.join(self.test_dir, "file1.xml")
        with open(self.file1_path, "w") as f:
            f.write("<CounselingRecord><PartnerClientNumber>1</PartnerClientNumber><ClientIntake><Race>Asian</Race></ClientIntake></CounselingRecord>")

        self.file2_path = os.path.join(self.test_dir, "file2.xml")
        with open(self.file2_path, "w") as f:
            f.write("<CounselingRecord><PartnerClientNumber>2</PartnerClientNumber><ClientIntake><Ethnicity>Hispanic</Ethnicity></ClientIntake></CounselingRecord>")

        # Create a non-XML file
        self.text_file_path = os.path.join(self.test_dir, "file3.txt")
        with open(self.text_file_path, "w") as f:
            f.write("This is a text file, not XML.")

        # Create a subdirectory with an XML file
        self.sub_dir = os.path.join(self.test_dir, "subdir")
        os.makedirs(self.sub_dir)
        self.file4_path = os.path.join(self.sub_dir, "file4.xml")
        with open(self.file4_path, "w") as f:
            f.write("<CounselingRecord><PartnerClientNumber>4</PartnerClientNumber></CounselingRecord>")

    def tearDown(self):
        # Remove the directory after the test
        shutil.rmtree(self.test_dir)

    def test_process_directory_basic(self):
        """Test processing a directory without recursive search, output_dir, or fixing."""
        processed_count = xml_validator.process_directory(self.test_dir, recursive=False)
        self.assertEqual(processed_count, 2)  # file1.xml and file2.xml

    def test_process_directory_recursive(self):
        """Test processing a directory with recursive search enabled."""
        processed_count = xml_validator.process_directory(self.test_dir, recursive=True)
        self.assertEqual(processed_count, 3)  # file1.xml, file2.xml, and subdir/file4.xml

    @patch('xml_validator.fix_client_intake_element_order')
    def test_process_directory_with_output_dir(self, mock_fix):
        """Test processing a directory and saving to an output directory."""
        # By default process_directory does not copy files if fix=False!
        # It only calculates current_output_path.
        # But if fix=True, it will try to fix the files to the output dir.
        mock_fix.return_value = True
        output_dir = os.path.join(self.test_dir, "output")

        processed_count = xml_validator.process_directory(self.test_dir, output_dir=output_dir, fix=True, recursive=False)

        self.assertEqual(processed_count, 2)
        # Verify output directory was created
        self.assertTrue(os.path.exists(output_dir))

        # Verify fix was called with correct output path mapping
        mock_fix.assert_any_call(self.file1_path, os.path.join(output_dir, "file1.xml"), False)
        mock_fix.assert_any_call(self.file2_path, os.path.join(output_dir, "file2.xml"), False)

    @patch('xml_validator.fix_client_intake_element_order')
    def test_process_directory_recursive_with_output_dir(self, mock_fix):
        """Test recursive processing with an output directory preserves structure."""
        mock_fix.return_value = True
        output_dir = os.path.join(self.test_dir, "output_recursive")
        processed_count = xml_validator.process_directory(self.test_dir, output_dir=output_dir, fix=True, recursive=True)

        self.assertEqual(processed_count, 3)
        self.assertTrue(os.path.exists(output_dir))

        # Output sub-directory is created BEFORE fix is called
        self.assertTrue(os.path.exists(os.path.join(output_dir, "subdir")))

        mock_fix.assert_any_call(self.file4_path, os.path.join(output_dir, "subdir", "file4.xml"), False)

    @patch('xml_validator.validate_against_xsd')
    def test_process_directory_with_xsd_validation(self, mock_validate):
        """Test processing with XSD validation enabled."""
        mock_validate.return_value = (True, [])
        xsd_file = os.path.join(self.test_dir, "dummy.xsd")
        with open(xsd_file, "w") as f:
            f.write("<schema></schema>")

        # process_directory counts files differently if validation is done but no fix
        # Ah! Note in the code:
        # elif not xsd_file: processed_count += 1
        # If xsd_file is provided but fix is False, processed_count stays 0!
        processed_count = xml_validator.process_directory(self.test_dir, xsd_file=xsd_file, recursive=False)

        self.assertEqual(processed_count, 0)
        self.assertEqual(mock_validate.call_count, 2)

    @patch('xml_validator.fix_client_intake_element_order')
    def test_process_directory_with_fix(self, mock_fix):
        """Test processing with fix flag enabled."""
        mock_fix.return_value = True

        processed_count = xml_validator.process_directory(self.test_dir, fix=True, recursive=False)

        self.assertEqual(processed_count, 2)
        self.assertEqual(mock_fix.call_count, 2)

        # Verify fix was called with correct arguments
        mock_fix.assert_any_call(self.file1_path, self.file1_path, False)

    @patch('xml_validator.fix_client_intake_element_order')
    @patch('xml_validator.validate_against_xsd')
    def test_process_directory_fix_and_validate(self, mock_validate, mock_fix):
        """Test processing with fix and XSD validation."""
        mock_validate.side_effect = [(False, ["error"]), (True, []), (False, ["error"]), (True, [])] # Original then fixed for both files
        mock_fix.return_value = True

        xsd_file = os.path.join(self.test_dir, "dummy.xsd")

        processed_count = xml_validator.process_directory(self.test_dir, xsd_file=xsd_file, fix=True, recursive=False)

        self.assertEqual(processed_count, 2)
        # Validate should be called 4 times total (before and after fix for each file)
        self.assertEqual(mock_validate.call_count, 4)
        self.assertEqual(mock_fix.call_count, 2)

    def test_process_empty_directory(self):
        """Test processing an empty directory returns 0."""
        empty_dir = tempfile.mkdtemp()
        try:
            processed_count = xml_validator.process_directory(empty_dir)
            self.assertEqual(processed_count, 0)
        finally:
            shutil.rmtree(empty_dir)


class TestFixClientIntakeElementOrder(unittest.TestCase):

    @patch('xml_validator.ET.parse')
    @patch('xml_validator.logger.error')
    def test_fix_client_intake_element_order_exception(self, mock_logger, mock_parse):
        """Test the exception path for fix_client_intake_element_order."""
        mock_parse.side_effect = Exception("Test exception")

        result = xml_validator.fix_client_intake_element_order("dummy.xml")

        self.assertFalse(result)
        mock_logger.assert_called_once_with("Error fixing XML file: Test exception")


    def test_fix_client_intake_element_order_success(self):
        """Test the success path for fix_client_intake_element_order."""
        # Create a temporary dummy XML file to test order
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<Root>
    <CounselingRecord>
        <PartnerClientNumber>12345</PartnerClientNumber>
        <ClientIntake>
            <MilitaryStatus>Active</MilitaryStatus>
            <Race>White</Race>
            <Disability>No</Disability>
            <Ethnicity>Non-Hispanic</Ethnicity>
            <Sex>Male</Sex>
        </ClientIntake>
    </CounselingRecord>
</Root>
"""
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.xml') as f:
            f.write(xml_content)
            temp_file = f.name

        try:
            # We want to use the function to fix the order
            result = xml_validator.fix_client_intake_element_order(temp_file)
            self.assertTrue(result)

            # Now parse it back to check order
            tree = xml_validator.ET.parse(temp_file)
            root = tree.getroot()
            client_intake = root.find('.//ClientIntake')

            # The expected order for these specific elements:
            expected_order = ['Race', 'Ethnicity', 'Sex', 'Disability', 'MilitaryStatus']
            actual_order = [child.tag for child in client_intake]

            self.assertEqual(expected_order, actual_order)
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

if __name__ == '__main__':
    unittest.main()
