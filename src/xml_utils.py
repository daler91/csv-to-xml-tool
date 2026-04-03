import xml.etree.ElementTree as ET


def create_element(parent: ET.Element, element_name: str, element_text: str = None) -> ET.Element:
    """
    Creates a new sub-element under the parent, sets its text if provided, and returns the new sub-element.

    Note: xml.etree.ElementTree automatically escapes special characters (&, <, >, etc.)
    when writing text content via the .text property, so manual escaping is not needed.
    """
    element = ET.SubElement(parent, element_name)
    if element_text is not None:
        element.text = element_text
    return element
