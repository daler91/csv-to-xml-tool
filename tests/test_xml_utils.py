import unittest
import xml.etree.ElementTree as ET
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.xml_utils import create_element

class TestXmlElementCreation(unittest.TestCase):

    def test_create_element_with_text(self):
        parent = ET.Element("root")
        element = create_element(parent, "child", "Hello World")
        self.assertEqual(element.tag, "child")
        self.assertEqual(element.text, "Hello World")
        self.assertIs(parent.find("child"), element)

    def test_create_element_without_text(self):
        parent = ET.Element("root")
        element = create_element(parent, "child")
        self.assertEqual(element.tag, "child")
        self.assertIsNone(element.text)
        self.assertIs(parent.find("child"), element)

    def test_create_element_under_parent(self):
        root = ET.Element("root")
        parent_element = create_element(root, "parent")
        child_element = create_element(parent_element, "child", "Child Text")

        self.assertIs(root.find("parent"), parent_element)
        self.assertIs(parent_element.find("child"), child_element)
        self.assertEqual(child_element.text, "Child Text")

    def test_create_element_auto_escapes_special_chars(self):
        """Verify that ET automatically escapes XML special characters in text content."""
        parent = ET.Element("root")
        element = create_element(parent, "child", 'Test & "quotes" <tag>')
        self.assertEqual(element.text, 'Test & "quotes" <tag>')
        xml_str = ET.tostring(parent, encoding="unicode")
        self.assertIn("&amp;", xml_str)
        self.assertIn("&lt;", xml_str)

if __name__ == '__main__':
    unittest.main()
