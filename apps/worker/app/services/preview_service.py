"""CSV preview and column detection for the web UI."""

import csv
import difflib
import os
import sys

_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.config import CounselingConfig, TrainingConfig

from ..core.security import DATA_DIR

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


def get_expected_columns(converter_type: str) -> list[str]:
    if converter_type == "counseling":
        return COUNSELING_EXPECTED
    elif converter_type == "training":
        # Flatten all possible header names
        all_headers = []
        for key, alts in TrainingConfig.COLUMN_MAPPING.items():
            all_headers.append(alts[0] if isinstance(alts, list) and alts else key)
        return all_headers
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

    return {
        "headers": list(headers),
        "rows": rows,
        "total_rows": total_rows,
        "column_status": {
            "matched": matched,
            "missing": missing,
            "extra": extra,
            "suggestions": suggestions,
        },
    }
