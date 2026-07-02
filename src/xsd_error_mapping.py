"""
Structured XSD error mapping (feature 2.4).

Turns the flat "Line N: Element 'X': ..." strings produced by
``xml_validator.validate_against_xsd`` into structured detail dicts that trace
each error back to the record (row) and CSV column it came from, so the web UI
can show "Row 3 (Contact 003XX000004TMM1): 'Date' (CSV column 'Date') — ..."
instead of a raw validator message.

Detail dict shape (all trackable fields nullable):
    {"line": int|None, "row_number": int|None, "record_id": str|None,
     "element": str|None, "field_label": str|None, "csv_column": str|None,
     "message": str, "friendly_message": str}
"""

import bisect
import os
import re

from lxml import etree

# Per schema type: (record element tag, identifier child tag, identifier kind
# shown in friendly messages). training-client output is Form 641
# counseling-format XML, so it shares the counseling shape.
_RECORD_SHAPES = {
    "counseling": ("CounselingRecord", "PartnerClientNumber", "Contact"),
    "training": ("ManagementTrainingRecord", "PartnerTrainingNumber", "Event"),
    "training-client": ("CounselingRecord", "PartnerClientNumber", "Contact"),
}

# Reverse map from XML element to the human field label and the CSV column the
# converter reads it from (derived from the row.get() calls in
# src/converters/counseling_converter.py). Keys are either a bare tag or
# "Parent/Tag" for generic child tags (Code, Date, ...) that need their parent
# for disambiguation; the "Parent/Tag" form is tried first.
_COUNSELING_ELEMENT_FIELDS = {
    "PartnerClientNumber": ("Contact ID", "Contact ID"),
    "LocationCode": ("Location Code", "LocationCode"),
    "Last": ("Last Name", "Last Name"),
    "First": ("First Name", "First Name"),
    "Middle": ("Middle Name", "Middle Name"),
    "Email": ("Email", "Email"),
    "Primary": ("Phone", "Contact: Phone"),
    "Secondary": ("Secondary Phone", "Contact: Secondary Phone"),
    "Street1": ("Mailing Street", "Mailing Street"),
    "City": ("Mailing City", "Mailing City"),
    "State": ("Mailing State/Province", "Mailing State/Province"),
    "ZipCode": ("Mailing Zip/Postal Code", "Mailing Zip/Postal Code"),
    "Zip4Code": ("Mailing Zip/Postal Code (+4)", "Mailing Zip/Postal Code"),
    "Country/Code": ("Mailing Country", "Mailing Country"),
    "Country": ("Mailing Country", "Mailing Country"),
    "SurveyAgreement": ("Agree to Impact Survey", "Agree to Impact Survey"),
    "ClientSignature/Date": ("Client Signature - Date", "Client Signature - Date"),
    "OnFile": ("Client Signature(On File)", "Client Signature(On File)"),
    "Race": ("Race", "Race"),
    "Race/Code": ("Race", "Race"),
    "Ethnicity": ("Ethnicity", "Ethnicity:"),
    "Sex": ("Gender", "Gender"),
    "Disability": ("Disability", "Disability"),
    "MilitaryStatus": ("Veteran Status", "Veteran Status"),
    "BranchOfService": ("Branch Of Service", "Branch Of Service"),
    "Media": ("What Prompted you to contact us?", "What Prompted you to contact us?"),
    "Media/Code": ("What Prompted you to contact us?", "What Prompted you to contact us?"),
    "Media/Other": ("Internet (specify)", "Internet (specify)"),
    "Internet": ("Internet Usage", "InternetUsage"),
    "CurrentlyInBusiness": ("Currently In Business?", "Currently In Business?"),
    "CurrentlyExporting": ("Currently Exporting", "Are you currently exporting?(old)"),
    "CompanyName": ("Account Name", "Account Name"),
    "BusinessType": ("Type of Business", "Type of Business"),
    "BusinessOwnership/Female": ("Business Ownership - % Female", "Business Ownership - % Female(old)"),
    "ConductingBusinessOnline": ("Conduct Business Online?", "Conduct Business Online?"),
    "ClientIntake_Certified8a": ("8(a) Certified?", "8(a) Certified?(old)"),
    "Employee_Owned": ("Employee Owned", "Employee Owned"),
    "TotalNumberOfEmployees": ("Total Number of Employees", "Total Number of Employees"),
    "NumberOfEmployeesInExportingBusiness": (
        "Number of Employees in Exporting Business",
        "Number of Employees in Exporting Business",
    ),
    "GrossRevenues": ("Gross Revenues/Sales", "Gross Revenues/Sales"),
    "ProfitLoss": ("Profits/Losses", "Profits/Losses"),
    "LegalEntity": ("Legal Entity of Business", "Legal Entity of Business"),
    "LegalEntity/Code": ("Legal Entity of Business", "Legal Entity of Business"),
    "LegalEntity/Other": ("Other legal entity (specify)", "Other legal entity (specify)"),
    "Rural_vs_Urban": ("Rural vs Urban", "Rural_vs_Urban"),
    "FIPS_Code": ("FIPS Code", "FIPS_Code"),
    "CounselingSeeking": ("Nature of the Counseling Seeking?", "Nature of the Counseling Seeking?"),
    "CounselingSeeking/Code": ("Nature of the Counseling Seeking?", "Nature of the Counseling Seeking?"),
    "CounselingSeeking/Other": (
        "Nature of the Counseling Seeking - Other Detail",
        "Nature of the Counseling Seeking - Other Detail",
    ),
    "ExportCountries/Code": ("Export Countries", "Export Countries"),
    "PartnerSessionNumber": ("Activity ID", "Activity ID"),
    "FundingSource": ("Funding Source", "Funding Source"),
    "VerifiedToBeInBusiness": ("Verified To Be In Business", "Verified To Be In Business"),
    "ReportableImpact": ("Reportable Impact", "Reportable Impact"),
    "DateOfReportableImpact": ("Reportable Impact Date", "Reportable Impact Date"),
    "BusinessStartDatePart3": ("Business Start Date", "Business Start Date"),
    "SBALoanAmount": ("SBA Loan Amount", "SBA Loan Amount"),
    "NonSBALoanAmount": ("Non-SBA Loan Amount", "Non-SBA Loan Amount"),
    "EquityCapitalReceived": ("Amount of Equity Capital Received", "Amount of Equity Capital Received"),
    "Certifications/Code": ("Certifications", "Certifications (SDB, HUBZONE, etc)"),
    "Certifications/Other": ("Other Certifications", "Other Certifications"),
    "SBAFinancialAssistance/Code": ("SBA Financial Assistance", "SBA Financial Assistance"),
    "SBAFinancialAssistance/Other": ("Other SBA Financial Assistance", "Other SBA Financial Assistance"),
    "CounselingProvided/Code": ("Services Provided", "Services Provided"),
    "CounselingProvided/Other": ("Other Counseling Provided", "Other Counseling Provided"),
    "ReferredClient/Code": ("Referred Client to", "Referred Client to"),
    "ReferredClient/Other": ("Other (Referred Client to)", "Other (Referred Client to)"),
    "SessionType": ("Type of Session", "Type of Session"),
    "Language/Code": ("Language(s) Used", "Language(s) Used"),
    "Language/Other": ("Language(s) Used (Other)", "Language(s) Used (Other)"),
    "DateCounseled": ("Date", "Date"),
    "CounselorName": ("Name of Counselor", "Name of Counselor"),
    "Contact": ("Duration (hours)", "Duration (hours)"),
    "Prepare": ("Prep Hours", "Prep Hours"),
    "Travel": ("Travel Hours", "Travel Hours"),
    "CounselorNotes": ("Comments", "Comments"),
}

# Derived from TrainingConfig.COLUMN_MAPPING (canonical alias per key). The
# NumberTrained/* aggregates trace back to the per-attendee column they are
# counted from.
_TRAINING_ELEMENT_FIELDS = {
    "PartnerTrainingNumber": ("Class/Event ID", "Class/Event ID"),
    "FundingSource": ("Funding Source", "Funding Source"),
    "DateTrainingStarted": ("Start Date", "Start Date"),
    "TrainingTitle": ("Class/Event Name", "Class/Event Name"),
    "TrainingTopic": ("Training Topic", "Training Topic"),
    "TrainingTopic/Code": ("Training Topic", "Training Topic"),
    "ProgramFormatType": ("Class/Event Type", "Class/Event Type"),
    "CosponsorsName": ("Cosponsor", "Cosponsor"),
    "City": ("City", "City"),
    "State": ("State/Province", "State/Province"),
    "ZipCode": ("Zip/Postal Code", "Zip/Postal Code"),
    "NumberTrained/Female": ("Gender", "Gender"),
    "NumberTrained/Male": ("Gender", "Gender"),
    "NumberTrained/CurrentlyInBusiness": ("Currently in Business?", "Currently in Business?"),
    "NumberTrained/NotYetInBusiness": ("Currently in Business?", "Currently in Business?"),
    "NumberTrained/PersonWithDisabilities": ("Disabilities", "Disabilities"),
    "Race": ("Race", "Race"),
    "Ethnicity": ("Ethnicity", "Ethnicity"),
}

_ELEMENT_FIELD_MAPS = {
    "counseling": _COUNSELING_ELEMENT_FIELDS,
    "training": _TRAINING_ELEMENT_FIELDS,
    "training-client": _COUNSELING_ELEMENT_FIELDS,
}

# "Line 20: <validator message>" — the format validate_against_xsd emits.
_LINE_PREFIX_RE = re.compile(r"^Line (\d+): (.*)$", re.DOTALL)
# lxml schema errors lead with the offending element: "Element 'ZipCode': ..."
_ELEMENT_RE = re.compile(r"^Element '([^']+)'")
# "[facet 'pattern'] " style prefixes add nothing for end users.
_FACET_PREFIX_RE = re.compile(r"^\[[^\]]*\]\s*")


def _parse_xml(xml_source: str):
    """Parse XML content or an XML file path; None when unparseable.

    Mirrors xml_validator's parser settings (lxml with entity resolution
    disabled) so line numbers agree with the validation pass.
    """
    parser = etree.XMLParser(resolve_entities=False)
    try:
        if xml_source.lstrip().startswith("<"):
            # Content string; encode so an XML declaration is accepted.
            return etree.fromstring(xml_source.encode("utf-8"), parser).getroottree()
        if os.path.exists(xml_source):
            return etree.parse(xml_source, parser=parser)
    except (etree.XMLSyntaxError, ValueError, OSError):
        return None
    return None


def _enumerate_records(xml_source: str, record_tag: str, id_tag: str) -> list[tuple]:
    """Return [(start_line, row_number, record_id, record_element)] in document order."""
    tree = _parse_xml(xml_source)
    if tree is None:
        return []
    records = []
    for ordinal, record in enumerate(tree.getroot().iter(record_tag), 1):
        id_element = record.find(id_tag)
        record_id = None
        if id_element is not None and id_element.text and id_element.text.strip():
            record_id = id_element.text.strip()
        records.append((record.sourceline, ordinal, record_id, record))
    return records


def _record_for_line(records: list[tuple], line: int | None):
    """The record whose subtree contains the given line, or None.

    Records are in document order, so a line belongs to the last record that
    starts at or before it; a line before the first record is unmappable.
    """
    if line is None or not records:
        return None
    starts = [start for start, _, _, _ in records]
    index = bisect.bisect_right(starts, line) - 1
    return records[index] if index >= 0 else None


def _parent_tag_for(record, tag: str, line: int | None) -> str | None:
    """Tag of the parent of the element named ``tag`` at ``line`` in a record.

    Used to disambiguate generic child tags (Code, Date, Other, ...) via a
    "Parent/Tag" lookup. Prefers the exact source line; falls back to the sole
    occurrence when the tag appears exactly once in the record.
    """
    matches = list(record.iter(tag))
    for element in matches:
        if line is not None and element.sourceline == line:
            parent = element.getparent()
            return parent.tag if parent is not None else None
    if len(matches) == 1:
        parent = matches[0].getparent()
        return parent.tag if parent is not None else None
    return None


def _humanize_tag(tag: str) -> str:
    """Fallback field label: split a tag on underscores and camel-case."""
    spaced = re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", tag.replace("_", " ")
    )
    return re.sub(r"\s+", " ", spaced).strip()


def _resolve_field(element: str | None, parent_tag: str | None,
                   element_fields: dict) -> tuple[str | None, str | None]:
    """(field_label, csv_column) for an element, using the parent when known."""
    if not element:
        return None, None
    if parent_tag:
        hit = element_fields.get(f"{parent_tag}/{element}")
        if hit:
            return hit
    hit = element_fields.get(element)
    if hit:
        return hit
    return _humanize_tag(element), None


def _restatement(message: str, element: str | None) -> str:
    """Plain restatement: the raw message minus its element/facet prefixes."""
    rest = message
    if element:
        prefix = f"Element '{element}':"
        if rest.startswith(prefix):
            rest = rest[len(prefix):].strip()
    rest = _FACET_PREFIX_RE.sub("", rest, count=1)
    return rest or message


def _friendly_message(row_number: int | None, record_id: str | None, id_kind: str,
                      field_label: str | None, csv_column: str | None,
                      restatement: str) -> str:
    if row_number is not None:
        who = f"Row {row_number}"
        if record_id:
            who += f" ({id_kind} {record_id})"
        if field_label and csv_column:
            return f"{who}: '{field_label}' (CSV column '{csv_column}') — {restatement}"
        if field_label:
            return f"{who}: '{field_label}' — {restatement}"
        return f"{who}: {restatement}"
    if field_label:
        return f"'{field_label}': {restatement}"
    return restatement


def build_error_details(xml_source: str, errors: list[str], schema_type: str) -> list[dict]:
    """Map validator error strings back to records and CSV columns.

    Args:
        xml_source: The validated XML — either its content or a file path.
        errors: The error strings from validate_against_xsd
                (``"Line 20: Element 'ZipCode': ..."``).
        schema_type: "counseling" | "training" | "training-client".

    Returns:
        One detail dict per input error, in order. Unmappable pieces (no line,
        unknown element, unparseable XML, unknown schema type) degrade to None
        fields — never an exception.
    """
    shape = _RECORD_SHAPES.get(schema_type)
    element_fields = _ELEMENT_FIELD_MAPS.get(schema_type, {})
    records = _enumerate_records(xml_source, shape[0], shape[1]) if shape else []
    id_kind = shape[2] if shape else "Record"

    details = []
    for raw in errors:
        line = None
        message = raw
        line_match = _LINE_PREFIX_RE.match(raw)
        if line_match:
            line = int(line_match.group(1))
            message = line_match.group(2)

        element_match = _ELEMENT_RE.match(message)
        element = element_match.group(1) if element_match else None

        row_number = record_id = parent_tag = None
        record = _record_for_line(records, line)
        if record is not None:
            _, row_number, record_id, record_element = record
            if element:
                parent_tag = _parent_tag_for(record_element, element, line)

        field_label, csv_column = _resolve_field(element, parent_tag, element_fields)
        restatement = _restatement(message, element)
        details.append({
            "line": line,
            "row_number": row_number,
            "record_id": record_id,
            "element": element,
            "field_label": field_label,
            "csv_column": csv_column,
            "message": raw,
            "friendly_message": _friendly_message(
                row_number, record_id, id_kind, field_label, csv_column, restatement
            ),
        })
    return details
