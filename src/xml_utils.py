import xml.etree.ElementTree as ET

def create_element(parent: ET.Element, element_name: str, element_text: str = None) -> ET.Element:
    """
    Creates a new sub-element under the parent, sets its text if provided, and returns the new sub-element.
    """
    element = ET.SubElement(parent, element_name)
    if element_text is not None:
        element.text = element_text
    return element

def escape_xml(text: str | None = None) -> str:
    """
    Replaces XML special characters (&, <, >, ", ') with their corresponding entities.
    Returns an empty string if the input is None.
    """
    if text is None:
        return ""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace("\"", "&quot;")
    text = text.replace("'", "&apos;")
    return text
