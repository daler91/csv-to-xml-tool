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
            # Setup mock to raise an OSError (specific exception we now catch)
            mock_parse.side_effect = OSError("Test exception")

            # Call the function
            result = xml_validator.validate_against_xsd("dummy.xml", "dummy.xsd")

            # Verify the exception was caught and returned correctly
            self.assertFalse(result["is_valid"])
            self.assertGreater(len(result["errors"]), 0)


class TestProcessDirectory(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for testing
        self.test_dir = tempfile.mkdtemp()
        # process_directory confines --directory to SBA_OUTPUT_BASE (cwd by
        # default); the temp dir lives outside the checkout, so widen it.
        self._env = patch.dict(os.environ, {"SBA_OUTPUT_BASE": self.test_dir})
        self._env.start()

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
        self._env.stop()
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
        mock_validate.return_value = {"is_valid": True, "errors": []}
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
        mock_validate.side_effect = [{"is_valid": False, "errors": ["error"]}, {"is_valid": True, "errors": []}, {"is_valid": False, "errors": ["error"]}, {"is_valid": True, "errors": []}] # Original then fixed for both files
        mock_fix.return_value = True

        xsd_file = os.path.join(self.test_dir, "dummy.xsd")

        processed_count = xml_validator.process_directory(self.test_dir, xsd_file=xsd_file, fix=True, recursive=False)

        self.assertEqual(processed_count, 2)
        # Validate should be called 4 times total (before and after fix for each file)
        self.assertEqual(mock_validate.call_count, 4)
        self.assertEqual(mock_fix.call_count, 2)

    def test_process_empty_directory(self):
        """Test processing an empty directory returns 0."""
        empty_dir = tempfile.mkdtemp(dir=self.test_dir)
        processed_count = xml_validator.process_directory(empty_dir)
        self.assertEqual(processed_count, 0)

    def test_process_directory_refuses_input_outside_base(self):
        """--directory is confined to SBA_OUTPUT_BASE like --output (CWE-22)."""
        outside = tempfile.mkdtemp()
        try:
            with self.assertRaises(ValueError):
                xml_validator.process_directory(outside)
            via_parent = os.path.join(self.test_dir, "..", os.path.basename(outside))
            with self.assertRaises(ValueError):
                xml_validator.process_directory(via_parent)
        finally:
            shutil.rmtree(outside)

    def test_process_directory_rejects_pattern_with_a_directory_part(self):
        """--pattern is a file-name glob; a path such as ../*.xml is refused."""
        traversal = os.path.join("..", "*.xml")
        with self.assertRaises(ValueError):
            xml_validator.process_directory(self.sub_dir, pattern=traversal)

    def test_process_directory_skips_symlink_escaping_input_dir(self):
        """A symlink inside --directory that points outside it is not processed."""
        outside = tempfile.mkdtemp()
        try:
            with open(os.path.join(outside, "escape.xml"), "w") as f:
                f.write("<CounselingRecord/>")
            os.symlink(os.path.join(outside, "escape.xml"), os.path.join(self.sub_dir, "link.xml"))
            processed_count = xml_validator.process_directory(self.sub_dir)
        finally:
            shutil.rmtree(outside)
        # file4.xml is listed; the escaping link is not.
        self.assertEqual(processed_count, 1)


class TestFixClientIntakeElementOrder(unittest.TestCase):

    @patch('xml_validator.etree.parse')
    @patch('xml_validator.logger.error')
    def test_fix_client_intake_element_order_exception(self, mock_logger, mock_parse):
        """Test the exception path for fix_client_intake_element_order."""
        mock_parse.side_effect = OSError("Test exception")

        result = xml_validator.fix_client_intake_element_order("dummy.xml")

        self.assertFalse(result)
        mock_logger.assert_called_once_with("Could not fix dummy.xml: Could not read the file: Test exception")


    def test_fix_client_intake_element_order_success(self):
        """Test the success path for fix_client_intake_element_order."""
        # Create a temporary dummy XML file to test order. The root is SBA's:
        # the order now comes from the schema that root element belongs to.
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<CounselingInformation>
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
</CounselingInformation>
"""
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.xml') as f:
            f.write(xml_content)
            temp_file = f.name

        try:
            # We want to use the function to fix the order
            result = xml_validator.fix_client_intake_element_order(temp_file)
            self.assertTrue(result)

            # Now parse it back to check order
            tree = xml_validator.etree.parse(temp_file)
            root = tree.getroot()
            client_intake = root.find('.//ClientIntake')

            # The expected order for these specific elements:
            expected_order = ['Race', 'Ethnicity', 'Sex', 'Disability', 'MilitaryStatus']
            actual_order = [child.tag for child in client_intake]

            self.assertEqual(expected_order, actual_order)
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_GOLDEN_COUNSELING = os.path.join(_REPO_ROOT, 'tests', 'golden', 'sample_counseling.xml')
_GOLDEN_TRAINING = os.path.join(_REPO_ROOT, 'tests', 'golden', 'sample_training.xml')
_COUNSELING_XSD = os.path.join(_REPO_ROOT, 'schemas', 'SBA_NEXUS_Counseling-2-14.xsd')
_TRAINING_XSD = os.path.join(_REPO_ROOT, 'schemas', 'SBA_NEXUS_Training-2-25-2025.xsd')


def _move_to_end(parent, tag):
    child = parent.find(tag)
    parent.remove(child)
    parent.append(child)


class _FixerCase(unittest.TestCase):
    """Writes a mutated golden file to a temp dir for the fixer."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def golden(self, path=_GOLDEN_COUNSELING):
        return xml_validator.etree.parse(path)

    def write(self, content, name='in.xml'):
        path = os.path.join(self.tmp, name)
        if isinstance(content, str):
            with open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(content)
        else:
            content.write(path, encoding='utf-8', xml_declaration=True)
        return path

    def read(self, path):
        with open(path, encoding='utf-8', newline='') as f:
            return f.read()

    def golden_body(self):
        """The golden counseling file without its XML declaration."""
        return self.read(_GOLDEN_COUNSELING).split('?>', 1)[1]

    def misordered_body(self):
        """golden_body with Race moved to the end of the first ClientIntake."""
        tree = self.golden()
        _move_to_end(tree.getroot().find('CounselingRecord/ClientIntake'), 'Race')
        return xml_validator.etree.tostring(tree.getroot(), encoding='unicode')


class TestFixEveryElementOrder(_FixerCase):
    """The fixer reordered ClientIntake's children only, from a hand-kept list:
    an element out of place anywhere else stayed there, and the file failed."""

    def test_orders_every_sequence_not_just_client_intake(self):
        tree = self.golden()
        record = tree.getroot().find('CounselingRecord')
        _move_to_end(record.find('CounselorRecord'), 'Language')
        _move_to_end(record, 'ClientRequest')            # the record's own sequence
        _move_to_end(record, 'PartnerClientNumber')
        race = record.find('ClientIntake/Race')
        described = race.makeelement('SelfDescribedRace', {})
        described.text = 'Two or More Races'
        race.insert(0, described)                        # a nested one
        source = self.write(tree)
        self.assertFalse(xml_validator.validate_against_xsd(source, _COUNSELING_XSD)['is_valid'])

        output = os.path.join(self.tmp, 'out.xml')
        self.assertTrue(xml_validator.fix_client_intake_element_order(source, output))

        self.assertEqual(xml_validator.validate_against_xsd(output, _COUNSELING_XSD),
                         {'is_valid': True, 'errors': []})

    def test_orders_training_xml_by_its_own_schema(self):
        tree = self.golden(_GOLDEN_TRAINING)
        _move_to_end(tree.getroot().find('ManagementTrainingRecord'), 'Location')
        source = self.write(tree)

        output = os.path.join(self.tmp, 'out.xml')

        result = xml_validator.fix_element_order(source, output)

        self.assertEqual((result.ok, result.reordered), (True, 1))
        self.assertEqual(os.path.basename(result.xsd_file), os.path.basename(_TRAINING_XSD))
        self.assertEqual(xml_validator.validate_against_xsd(output, _TRAINING_XSD), {'is_valid': True, 'errors': []})

    def test_repeats_keep_their_order_and_unknown_tags_go_last(self):
        parent = xml_validator.etree.fromstring('<p><B/><X n="1"/><A n="1"/><A n="2"/><X n="2"/></p>')

        self.assertTrue(xml_validator.reorder_elements(parent, ['A', 'B']))

        self.assertEqual([(c.tag, c.get('n')) for c in parent],
                         [('A', '1'), ('A', '2'), ('B', None), ('X', '1'), ('X', '2')])
        self.assertFalse(xml_validator.reorder_elements(parent, ['A', 'B']))

    def test_whitespace_stays_put_and_comments_move_with_their_element(self):
        parent = xml_validator.etree.fromstring('<p>\n  <B/>\n  <!-- about A -->\n  <A/>\n</p>')

        xml_validator.reorder_elements(parent, ['A', 'B'])

        self.assertEqual(xml_validator.etree.tostring(parent, encoding='unicode'),
                         '<p>\n  <!-- about A -->\n  <A/>\n  <B/>\n</p>')

    def test_a_file_with_no_sba_root_is_refused(self):
        source = self.write('<Root><CounselingRecord/></Root>')
        output = os.path.join(self.tmp, 'out.xml')

        result = xml_validator.fix_element_order(source, output)

        self.assertFalse(result.ok)
        self.assertIn('The root element is <Root>', result.error)
        self.assertFalse(os.path.exists(output))


class TestFixChangesOnlyTheOrder(_FixerCase):
    """The fixer read with defusedxml/expat and wrote with ElementTree, unlike
    the validator (lxml): it applied DTD attribute defaults, wrote a CR given
    as &#13; back raw (so every reader then saw LF), and dropped comments,
    processing instructions and the DOCTYPE."""

    def test_dtd_attribute_defaults_are_not_made_real(self):
        source = self.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                            '<!DOCTYPE CounselingInformation [\n'
                            '  <!ATTLIST CounselingRecord foo CDATA "bar">\n]>' + self.misordered_body())
        output = os.path.join(self.tmp, 'out.xml')

        self.assertTrue(xml_validator.fix_client_intake_element_order(source, output))

        self.assertEqual(xml_validator.validate_against_xsd(output, _COUNSELING_XSD),
                         {'is_valid': True, 'errors': []})
        fixed = self.read(output)
        self.assertNotIn('foo="bar"', fixed)
        self.assertIn('<!ATTLIST CounselingRecord foo CDATA "bar">', fixed)

    def test_carriage_returns_comments_and_pis_come_through(self):
        notes = '<CounselorNotes>Discussed loan options.&#13;\nFollow up in March.</CounselorNotes>'
        body = self.misordered_body().replace('</CounselorRecord>', notes + '</CounselorRecord>', 1)
        body = body.replace('<CounselingRecord>', '<!-- reviewed by J. Smith --><?review ok?><CounselingRecord>', 1)
        source = self.write('<?xml version="1.0" encoding="UTF-8"?>\n' + body)
        output = os.path.join(self.tmp, 'out.xml')

        self.assertTrue(xml_validator.fix_client_intake_element_order(source, output))

        self.assertTrue(xml_validator.validate_against_xsd(output, _COUNSELING_XSD)['is_valid'])
        fixed = self.read(output)
        self.assertIn('Discussed loan options.&#13;\nFollow up in March.', fixed)
        self.assertIn('<!-- reviewed by J. Smith --><?review ok?>', fixed)

    def test_a_file_already_in_order_is_left_alone(self):
        source = self.write(self.read(_GOLDEN_COUNSELING).replace('<CounselingRecord>', '<!-- kept --><CounselingRecord>'))
        os.utime(source, ns=(0, 0))
        output = os.path.join(self.tmp, 'out.xml')

        self.assertTrue(xml_validator.fix_client_intake_element_order(source))
        self.assertTrue(xml_validator.fix_client_intake_element_order(source, output))

        self.assertEqual(os.stat(source).st_mtime_ns, 0)  # not rewritten
        self.assertEqual(self.read(output), self.read(source))
        self.assertFalse(xml_validator.fix_element_order(source).changed)


class TestEntityDeclarations(_FixerCase):
    """An internal entity came back from the validator as an opaque error, and
    the fixer refused a declared one without saying so to the web."""

    def with_doctype(self, subset, body):
        return f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE CounselingInformation [{subset}]>{body}'

    def test_validator_says_entities_are_not_supported(self):
        body = self.golden_body().replace('<CounselorName>Pat Smith</CounselorName>',
                                          '<CounselorName>&counselor;</CounselorName>')
        source = self.write(self.with_doctype('<!ENTITY counselor "Pat Smith">', body))

        result = xml_validator.validate_against_xsd(source, _COUNSELING_XSD)

        self.assertFalse(result['is_valid'])
        self.assertEqual(len(result['errors']), 1)
        self.assertTrue(result['errors'][0].startswith(xml_validator.ENTITIES_NOT_SUPPORTED), result['errors'])
        self.assertIn('&counselor;', result['errors'][0])

    def test_fixer_refuses_a_declared_entity_and_says_why(self):
        source = self.write(self.with_doctype('<!ENTITY nbsp "&#160;">', self.misordered_body()))
        output = os.path.join(self.tmp, 'out.xml')

        result = xml_validator.fix_element_order(source, output)

        self.assertFalse(result.ok)
        self.assertTrue(result.error.startswith(xml_validator.ENTITIES_NOT_SUPPORTED), result.error)
        self.assertFalse(os.path.exists(output))

    def test_entity_expansion_and_external_entities_stay_refused(self):
        # What defusedxml guarded the fixer against: a billion laughs, and an
        # external entity reading a local file.
        laughs = '<!ENTITY lol "lol">' + ''.join(
            f'<!ENTITY lol{i} "{("&lol%d;" % (i - 1) if i > 1 else "&lol;") * 10}">' for i in range(1, 10))
        cases = {
            'billion laughs': self.with_doctype(laughs, '<CounselingInformation>&lol9;</CounselingInformation>'),
            'external entity': self.with_doctype(f'<!ENTITY x SYSTEM "file://{_GOLDEN_COUNSELING}">',
                                                 '<CounselingInformation>&x;</CounselingInformation>'),
        }
        for name, content in cases.items():
            with self.subTest(name):
                source = self.write(content)
                output = os.path.join(self.tmp, 'out.xml')
                result = xml_validator.fix_element_order(source, output)
                self.assertFalse(result.ok)
                self.assertFalse(os.path.exists(output))
                validation = xml_validator.validate_against_xsd(source, _COUNSELING_XSD)
                self.assertFalse(validation['is_valid'])
                self.assertNotIn('PartnerClientNumber', ' '.join(validation['errors']))


if __name__ == '__main__':
    unittest.main()
