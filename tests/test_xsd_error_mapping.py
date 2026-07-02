"""Unit tests for src/xsd_error_mapping.py (feature 2.4).

build_error_details turns the flat "Line N: Element 'X': ..." strings from
validate_against_xsd into structured detail dicts: the error line is mapped to
the enclosing record (1-based row_number + its identifier text) and the element
is mapped back to the CSV column the converter reads it from. Unmappable pieces
degrade to None fields, never an exception.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.xsd_error_mapping import build_error_details

# Explicit fixture strings so source lines are known; tests look line numbers
# up by content (via _line_of) so edits don't silently break the assertions.
COUNSELING_XML = """<?xml version='1.0' encoding='utf-8'?>
<CounselingInformation>
  <CounselingRecord>
    <PartnerClientNumber>C-001</PartnerClientNumber>
    <ClientRequest>
      <AddressPart1>
        <ZipCode>50309</ZipCode>
      </AddressPart1>
    </ClientRequest>
    <ClientIntake>
      <Race>
        <Code>White</Code>
      </Race>
    </ClientIntake>
  </CounselingRecord>
  <CounselingRecord>
    <PartnerClientNumber>C-002</PartnerClientNumber>
    <ClientRequest>
      <AddressPart1>
        <ZipCode>BAD</ZipCode>
      </AddressPart1>
    </ClientRequest>
    <CounselorRecord>
      <DateCounseled>2025-13-45</DateCounseled>
    </CounselorRecord>
  </CounselingRecord>
</CounselingInformation>
"""

TRAINING_XML = """<?xml version='1.0' encoding='utf-8'?>
<ManagementTrainingReport>
  <ManagementTrainingRecord>
    <PartnerTrainingNumber>EVT-1</PartnerTrainingNumber>
    <DateTrainingStarted>2025-01-15</DateTrainingStarted>
  </ManagementTrainingRecord>
  <ManagementTrainingRecord>
    <PartnerTrainingNumber>EVT-2</PartnerTrainingNumber>
    <DateTrainingStarted>bogus</DateTrainingStarted>
  </ManagementTrainingRecord>
</ManagementTrainingReport>
"""


def _line_of(xml_text, needle):
    """1-based line number of the first line containing needle."""
    for i, line in enumerate(xml_text.splitlines(), 1):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not found in fixture")


def _one_detail(xml_text, error, schema_type="counseling"):
    details = build_error_details(xml_text, [error], schema_type)
    assert len(details) == 1
    return details[0]


def test_line_maps_to_enclosing_record_and_id():
    line = _line_of(COUNSELING_XML, "<ZipCode>BAD</ZipCode>")
    error = (
        f"Line {line}: Element 'ZipCode': [facet 'pattern'] The value 'BAD' "
        f"is not accepted by the pattern '[0-9]{{5}}'."
    )
    detail = _one_detail(COUNSELING_XML, error)

    assert detail["line"] == line
    assert detail["row_number"] == 2  # second CounselingRecord
    assert detail["record_id"] == "C-002"
    assert detail["element"] == "ZipCode"
    assert detail["field_label"] == "Mailing Zip/Postal Code"
    assert detail["csv_column"] == "Mailing Zip/Postal Code"
    assert detail["message"] == error  # raw validator string kept verbatim
    # Friendly restatement: row + field + CSV column + message tail (element
    # prefix and "[facet ...]" chunk stripped).
    assert detail["friendly_message"] == (
        "Row 2 (Contact C-002): 'Mailing Zip/Postal Code' "
        "(CSV column 'Mailing Zip/Postal Code') — The value 'BAD' is not "
        "accepted by the pattern '[0-9]{5}'."
    )


def test_element_maps_to_csv_column():
    line = _line_of(COUNSELING_XML, "<DateCounseled>")
    error = f"Line {line}: Element 'DateCounseled': '2025-13-45' is not a valid value of the atomic type 'xs:date'."
    detail = _one_detail(COUNSELING_XML, error)

    assert detail["row_number"] == 2
    assert detail["field_label"] == "Date"
    assert detail["csv_column"] == "Date"
    assert detail["friendly_message"].startswith(
        "Row 2 (Contact C-002): 'Date' (CSV column 'Date') — "
    )


def test_generic_code_tag_is_disambiguated_by_parent():
    # 'Code' appears under many parents; the element at the error line sits
    # under <Race>, so it must resolve to the Race CSV column.
    line = _line_of(COUNSELING_XML, "<Code>White</Code>")
    error = (
        f"Line {line}: Element 'Code': [facet 'enumeration'] The value "
        f"'Purple' is not accepted."
    )
    detail = _one_detail(COUNSELING_XML, error)

    assert detail["row_number"] == 1
    assert detail["record_id"] == "C-001"
    assert detail["field_label"] == "Race"
    assert detail["csv_column"] == "Race"


def test_unknown_element_falls_back_to_humanized_label():
    line = _line_of(COUNSELING_XML, "<Race>")
    error = f"Line {line}: Element 'FrobnicatorSetting': something is wrong here."
    detail = _one_detail(COUNSELING_XML, error)

    assert detail["row_number"] == 1  # line still maps to the record
    assert detail["element"] == "FrobnicatorSetting"
    assert detail["field_label"] == "Frobnicator Setting"  # camel-case split
    assert detail["csv_column"] is None
    assert detail["friendly_message"] == (
        "Row 1 (Contact C-001): 'Frobnicator Setting' — something is wrong here."
    )


def test_line_outside_any_record_is_unmappable():
    # Line 2 is the root element, before the first CounselingRecord.
    error = "Line 2: Element 'CounselingInformation': Missing child element(s)."
    detail = _one_detail(COUNSELING_XML, error)

    assert detail["line"] == 2
    assert detail["row_number"] is None
    assert detail["record_id"] is None
    # Row-less fallback: "'<field_label>': <restatement>".
    assert detail["friendly_message"] == (
        "'Counseling Information': Missing child element(s)."
    )


def test_error_without_line_prefix_degrades_to_raw_message():
    detail = _one_detail(COUNSELING_XML, "Validation error")

    assert detail["line"] is None
    assert detail["row_number"] is None
    assert detail["element"] is None
    assert detail["field_label"] is None
    assert detail["csv_column"] is None
    assert detail["message"] == "Validation error"
    assert detail["friendly_message"] == "Validation error"


def test_unparseable_xml_degrades_to_unmapped_details():
    error = "XML parse error: Start tag expected, '<' not found, line 1, column 1"
    detail = _one_detail("this is not xml <", error)

    assert detail["row_number"] is None
    assert detail["record_id"] is None
    assert detail["message"] == error


def test_training_records_map_by_event_number():
    line = _line_of(TRAINING_XML, "<DateTrainingStarted>bogus")
    error = f"Line {line}: Element 'DateTrainingStarted': 'bogus' is not a valid value of the atomic type 'xs:date'."
    detail = _one_detail(TRAINING_XML, error, schema_type="training")

    assert detail["row_number"] == 2  # second ManagementTrainingRecord
    assert detail["record_id"] == "EVT-2"
    assert detail["field_label"] == "Start Date"
    assert detail["csv_column"] == "Start Date"
    assert detail["friendly_message"].startswith(
        "Row 2 (Event EVT-2): 'Start Date' (CSV column 'Start Date') — "
    )


def test_accepts_a_file_path_as_xml_source(tmp_path):
    xml_path = tmp_path / "records.xml"
    xml_path.write_text(COUNSELING_XML, encoding="utf-8")
    line = _line_of(COUNSELING_XML, "<ZipCode>BAD</ZipCode>")
    error = f"Line {line}: Element 'ZipCode': [facet 'pattern'] The value 'BAD' is not accepted by the pattern '[0-9]{{5}}'."

    detail = build_error_details(str(xml_path), [error], "counseling")[0]

    assert detail["row_number"] == 2
    assert detail["record_id"] == "C-002"


def test_training_client_uses_counseling_record_shape():
    line = _line_of(COUNSELING_XML, "<ZipCode>BAD</ZipCode>")
    error = f"Line {line}: Element 'ZipCode': bad value."
    detail = _one_detail(COUNSELING_XML, error, schema_type="training-client")

    assert detail["row_number"] == 2
    assert detail["record_id"] == "C-002"
    assert "Contact C-002" in detail["friendly_message"]
