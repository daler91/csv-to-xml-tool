"""CSV preview and column detection for the web UI."""

import csv
import difflib
import os
import sys

_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.config import CounselingConfig, TrainingConfig, TrainingClientConfig

from ..core.security import DATA_DIR

# Plain-language field metadata shown on the web mapping page.
# Added for UX_REVIEW.md §3.5 — the mapping page previously exposed
# raw XML field names like "BranchOfService" with no explanation of
# what they mean or when conditional rules apply.
#
# Keys are the expected field names (same keys used in the
# ``field_requirements`` map). Each value is a dict with:
#   - description: plain-language explanation of the field
#   - conditional_rule: present only when field_requirements is
#     "conditional" — describes the rule in words.
#
# Fields not listed here fall back to no description in the UI.
# Required and conditional fields should always have descriptions;
# optional fields are best-effort.

COUNSELING_FIELD_METADATA: dict[str, dict[str, str]] = {
    "Contact ID": {
        "description": "Salesforce Contact ID for the individual being counseled. Must be unique per client.",
    },
    "Last Name": {
        "description": "Client last (family) name.",
    },
    "First Name": {
        "description": "Client first (given) name.",
    },
    "Email": {
        "description": "Client email address. Used for optional impact-survey contact.",
    },
    "Contact: Phone": {
        "description": "Primary contact phone number. Non-digits are stripped during cleaning.",
    },
    "Mailing State/Province": {
        "description": "Client mailing state or province. Two-letter codes (e.g. IA) are expanded to full names during cleaning.",
    },
    "Mailing Country": {
        "description": "Client mailing country. Standardized to the SBA schema enumeration during cleaning.",
    },
    "Race": {
        "description": "Client race. Salesforce multi-value lists are split and mapped to schema codes.",
    },
    "Ethnicity:": {
        "description": "Client ethnicity (Hispanic/Latino status).",
    },
    "Gender": {
        "description": "Client gender.",
    },
    "Disability": {
        "description": "Whether the client has a self-reported disability.",
    },
    "Veteran Status": {
        "description": "Client military veteran status. Controls the BranchOfService conditional requirement.",
    },
    "Branch Of Service": {
        "description": "Branch of the U.S. armed forces the client served in.",
        "conditional_rule": "Required when Veteran Status indicates military service (Active, Veteran, Service-Disabled Veteran, etc.).",
    },
    "What Prompted you to contact us?": {
        "description": "How the client found out about SBA services. Controls the Internet conditional requirements.",
    },
    "Internet (specify)": {
        "description": "Specific internet source that prompted the client to contact SBA.",
        "conditional_rule": "Required when 'What Prompted you to contact us?' is set to an Internet option.",
    },
    "InternetUsage": {
        "description": "Type of internet usage the client reported.",
        "conditional_rule": "Required when 'What Prompted you to contact us?' is set to an Internet option.",
    },
    "Currently In Business?": {
        "description": "Whether the client currently operates a business. Drives several conditional business-detail requirements.",
    },
    "Legal Entity of Business": {
        "description": "Legal structure of the client's business (LLC, S-Corp, etc.).",
        "conditional_rule": "Required when Currently In Business? is Yes.",
    },
    "Other legal entity (specify)": {
        "description": "Free-text description of a non-standard legal entity.",
        "conditional_rule": "Required when Legal Entity of Business is Other.",
    },
    "Rural_vs_Urban": {
        "description": "Rural or urban classification for the client's business location.",
    },
    "FIPS_Code": {
        "description": "Federal Information Processing Standards county code.",
        "conditional_rule": "Required when Rural_vs_Urban is populated.",
    },
    "Nature of the Counseling Seeking?": {
        "description": "Primary reason the client sought counseling.",
        "conditional_rule": "Required when Currently In Business? is Yes.",
    },
    "Nature of the Counseling Seeking - Other Detail": {
        "description": "Free-text description when the nature of counseling is 'Other'.",
        "conditional_rule": "Required when Nature of the Counseling Seeking? is Other.",
    },
    "Services Provided": {
        "description": "Salesforce multi-value list of counseling services rendered during the session.",
    },
    "Other Counseling Provided": {
        "description": "Free-text description of counseling provided when 'Other' is in Services Provided.",
        "conditional_rule": "Required when Services Provided includes Other.",
    },
    "Type of Session": {
        "description": "How the counseling was delivered (Face to Face, Telephone, Video, etc.).",
    },
    "Language(s) Used": {
        "description": "Language(s) the counseling was conducted in.",
    },
    "Date": {
        "description": "Date of the counseling session. Accepts common formats; normalized to YYYY-MM-DD.",
    },
    "Name of Counselor": {
        "description": "Name of the SBA counselor who conducted the session.",
    },
    "Duration (hours)": {
        "description": "Length of the counseling session in hours. Decimals allowed (e.g. 1.5).",
    },
    "Prep Hours": {
        "description": "Counselor preparation time in hours.",
    },
    "Travel Hours": {
        "description": "Counselor travel time in hours.",
    },
}

TRAINING_FIELD_METADATA: dict[str, dict[str, str]] = {
    "Class/Event ID": {
        "description": "Unique identifier for the training event. Rows with the same Class/Event ID are aggregated into one XML record.",
    },
}

TRAINING_CLIENT_FIELD_METADATA: dict[str, dict[str, str]] = {
    "Class/Event ID": {
        "description": "Identifier for the training event the attendee participated in.",
    },
    "Contact ID": {
        "description": "Salesforce Contact ID for the individual attendee. Must be unique within the event.",
    },
    "Training Topic": {
        "description": "Topic area of the training (Business Start-up, Marketing, etc.).",
    },
    "Class/Event Type": {
        "description": "Delivery format of the training (In-Person, Online, Hybrid).",
    },
    "Start Date": {
        "description": "Date the training session started. Accepts common formats; normalized to YYYY-MM-DD.",
    },
    "Ethnicity": {
        "description": "Attendee ethnicity (Hispanic/Latino status).",
    },
    "Race": {
        "description": "Attendee race. Salesforce multi-value lists are split and mapped to schema codes.",
    },
    "Gender": {
        "description": "Attendee gender.",
    },
    "Military Status": {
        "description": "Attendee military status.",
    },
    "Currently in Business?": {
        "description": "Whether the attendee currently operates a business.",
    },
}

# Field requirement levels: "required", "conditional", or "optional"
COUNSELING_REQUIRED = {
    "Contact ID", "Race", "Ethnicity:", "Gender", "Disability", "Veteran Status",
    "Currently In Business?", "Type of Session", "Language(s) Used",
    "Date", "Name of Counselor", "Duration (hours)",
}
COUNSELING_CONDITIONAL = {
    "Branch Of Service",              # required if military status
    "Internet (specify)",             # required if media=Internet
    "InternetUsage",                  # required if media=Internet
    "Legal Entity of Business",       # required if in business
    "Other legal entity (specify)",   # required if legal entity=Other
    "FIPS_Code",                      # required if Rural/Urban
    "Nature of the Counseling Seeking?",           # required if in business
    "Nature of the Counseling Seeking - Other Detail",  # required if seeking=Other
    "Other Counseling Provided",      # required if provided=Other
}

TRAINING_REQUIRED = {"Class/Event ID"}
TRAINING_CONDITIONAL: set[str] = set()

TRAINING_CLIENT_REQUIRED = {"Class/Event ID", "Contact ID"}
TRAINING_CLIENT_CONDITIONAL: set[str] = set()


def _build_field_requirements(
    expected: list[str],
    required: set[str],
    conditional: set[str],
) -> dict[str, str]:
    """Return a dict mapping each expected field to its requirement level."""
    result: dict[str, str] = {}
    for field in expected:
        if field in required:
            result[field] = "required"
        elif field in conditional:
            result[field] = "conditional"
        else:
            result[field] = "optional"
    return result


# Expected columns extracted from converter source code
COUNSELING_EXPECTED = [
    "Contact ID", "LocationCode", "Last Name", "First Name", "Middle Name",
    "Email", "Contact: Phone", "Contact: Secondary Phone",
    "Mailing Street", "Mailing City", "Mailing State/Province",
    "Mailing Zip/Postal Code", "Mailing Country",
    "Agree to Impact Survey", "Client Signature - Date", "Client Signature(On File)",
    "Race", "Ethnicity:", "Gender", "Disability", "Veteran Status",
    "Branch Of Service", "What Prompted you to contact us?",
    "Internet (specify)", "InternetUsage",
    "Currently In Business?", "Are you currently exporting?",
    "Account Name", "Type of Business",
    "Business Ownership - % Female", "Conduct Business Online?",
    "8(a) Certified?", "Total Number of Employees",
    "Number of Employees in Exporting Business",
    "Gross Revenues/Sales", "Profits/Losses",
    "Legal Entity of Business", "Other legal entity (specify)",
    "Rural_vs_Urban", "FIPS_Code",
    "Nature of the Counseling Seeking?",
    "Nature of the Counseling Seeking - Other Detail",
    "Activity ID", "Funding Source", "Verified To Be In Business",
    "Reportable Impact", "Reportable Impact Date",
    "Business Start Date", "Date Started (Meeting)",
    "Total No. of Employees (Meeting)",
    "Gross Revenues/Sales (Meeting)", "Profit & Loss (Meeting)",
    "SBA Loan Amount", "Non-SBA Loan Amount",
    "Amount of Equity Capital Received",
    "Certifications (SDB, HUBZONE, etc)", "Other Certifications",
    "SBA Financial Assistance", "Other SBA Financial Assistance",
    "Services Provided", "Other Counseling Provided",
    "Referred Client to", "Other (Referred Client to)",
    "Type of Session", "Language(s) Used", "Language(s) Used (Other)",
    "Date", "Name of Counselor", "Duration (hours)",
    "Prep Hours", "Travel Hours", "Comments",
]

# Training uses flexible COLUMN_MAPPING from config
TRAINING_EXPECTED = list(TrainingConfig.COLUMN_MAPPING.keys())

# Training client expected columns (the CSV columns before remapping)
TRAINING_CLIENT_EXPECTED = [
    "Class/Event ID", "Member Type", "First Name", "Last Name",
    "Member Status", "Company", "Phone", "Email",
    "Unique Campaign Members", "Currently in Business?",
    "Ethnicity", "Race", "Disabilities", "Gender", "Military Status",
    "Related Record ID", "Training Topic", "Class/Event Type",
    "Funding Source", "Member ID", "Class Teacher", "Contact ID",
    "Street", "city", "State", "Zip code", "Start Date", "Class/Event Name",
]


def get_expected_columns(converter_type: str) -> list[str]:
    if converter_type == "counseling":
        return COUNSELING_EXPECTED
    elif converter_type == "training":
        # Flatten all possible header names
        all_headers = []
        for key, alts in TrainingConfig.COLUMN_MAPPING.items():
            all_headers.append(alts[0] if isinstance(alts, list) and alts else key)
        return all_headers
    elif converter_type == "training-client":
        return TRAINING_CLIENT_EXPECTED
    return []


def read_csv_preview(csv_path: str, converter_type: str, max_rows: int = 20) -> dict:
    """Read first N rows of a CSV and detect column matching status.

    csv_path is a temp file created by the calling route from streamed content.
    """
    rows = []
    headers = []
    total_rows = 0

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        for i, row in enumerate(reader):
            total_rows += 1
            if i < max_rows:
                rows.append(dict(row))

    expected = get_expected_columns(converter_type)
    actual_set = set(headers)
    expected_set = set(expected)

    matched = sorted(actual_set & expected_set)
    missing = sorted(expected_set - actual_set)
    extra = sorted(actual_set - expected_set)

    # Fuzzy match suggestions for missing columns
    suggestions = []
    for m in missing:
        close = difflib.get_close_matches(m, list(extra), n=1, cutoff=0.6)
        if close:
            ratio = difflib.SequenceMatcher(None, m.lower(), close[0].lower()).ratio()
            suggestions.append({
                "csv_column": close[0],
                "suggested_match": m,
                "score": round(ratio * 100),
            })

    # Determine requirement level for each expected field
    if converter_type == "counseling":
        field_requirements = _build_field_requirements(expected, COUNSELING_REQUIRED, COUNSELING_CONDITIONAL)
        field_metadata = COUNSELING_FIELD_METADATA
    elif converter_type == "training":
        field_requirements = _build_field_requirements(expected, TRAINING_REQUIRED, TRAINING_CONDITIONAL)
        field_metadata = TRAINING_FIELD_METADATA
    elif converter_type == "training-client":
        field_requirements = _build_field_requirements(expected, TRAINING_CLIENT_REQUIRED, TRAINING_CLIENT_CONDITIONAL)
        field_metadata = TRAINING_CLIENT_FIELD_METADATA
    else:
        field_requirements = {}
        field_metadata = {}

    # Only emit metadata for fields we actually expect, so the payload
    # stays tight. Missing entries are silently omitted; the UI falls
    # back to rendering just the raw field name.
    field_descriptions: dict[str, dict[str, str]] = {
        field: field_metadata[field]
        for field in expected
        if field in field_metadata
    }

    return {
        "headers": list(headers),
        "rows": rows,
        "total_rows": total_rows,
        "column_status": {
            "matched": matched,
            "missing": missing,
            "extra": extra,
            "suggestions": suggestions,
            "field_requirements": field_requirements,
            "field_descriptions": field_descriptions,
        },
    }
