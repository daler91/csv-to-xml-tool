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


def emit_optional(parent: ET.Element, element_name: str, element_text) -> ET.Element | None:
    """Create a sub-element only when there is a value to put in it.

    Most optional elements in the SBA schemas are minOccurs="0" but carry a
    pattern, enumeration, or non-string base type (ZipCode is ``\\d{5}``, Date is
    ``xs:date``, hours are ``xs:decimal``). An element emitted with empty text
    therefore *fails* validation, where omitting it is perfectly valid -- so a
    blank cell must never produce ``<ZipCode/>``.

    Returns the new element, or None when the value was blank and nothing was
    emitted. Callers that need to attach children should check for None.
    """
    if element_text is None:
        return None
    text = str(element_text).strip()
    if not text:
        return None
    return create_element(parent, element_name, text)
