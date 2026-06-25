"""Required/conditional column tiers and conversion-time validation (CONV-1).

Single source of truth for which CSV columns each converter needs, shared by:

- ``preview_service.read_csv_preview`` — the mapping-page UI (matched/missing columns
  and required/conditional/optional badges).
- ``conversion_service.run_conversion`` — hard-fails a conversion when a *required*
  column is missing, and warns when a *conditional* or *fabrication-risk* column is
  missing, so absent source data is never silently defaulted into the federal XML.

Validation runs in ``conversion_service`` AFTER any user ``column_mapping`` has been
applied, so a CSV the user has correctly mapped is not falsely rejected.
"""

import csv
import os
import sys

_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.data_cleaning import normalize_header

# --- Requirement tiers (moved here from preview_service so preview and conversion
# share one definition). "required" -> hard-fail if missing; "conditional" -> warn. ---

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
    "Nature of the Counseling Seeking?",                 # required if in business
    "Nature of the Counseling Seeking - Other Detail",   # required if seeking=Other
    "Other Counseling Provided",      # required if provided=Other
}

TRAINING_REQUIRED = {"Class/Event ID"}
TRAINING_CONDITIONAL: set[str] = set()

TRAINING_CLIENT_REQUIRED = {"Class/Event ID", "Contact ID"}
TRAINING_CLIENT_CONDITIONAL: set[str] = set()

# Columns the counseling converter silently defaults to a *non-empty* value when the
# column is absent -- i.e. it fabricates data that ships in the federal XML. Exact
# header strings are taken from counseling_converter.py's row.get(...) calls so the
# check matches what the converter actually reads:
#   Gross Revenues/Sales, Profits/Losses, SBA/Non-SBA Loan, Equity Capital -> "0"
#   Business Ownership - % Female(old) -> 0 ; Mailing Country -> "United States"
#   Conduct Business Online?, 8(a) Certified?(old) -> "No"
# The "(Meeting)" revenue/profit variants are intentionally excluded: the converter
# falls back to the base "Gross Revenues/Sales" / "Profits/Losses" columns (already
# listed), so warning on the variants too would just be noise.
COUNSELING_FABRICATION_DEFAULTS = {
    "Gross Revenues/Sales",
    "Profits/Losses",
    "SBA Loan Amount",
    "Non-SBA Loan Amount",
    "Amount of Equity Capital Received",
    "Business Ownership - % Female(old)",
    "Mailing Country",
    "Conduct Business Online?",
    "8(a) Certified?(old)",
}


class RequiredColumnsMissingError(Exception):
    """Raised when an uploaded CSV lacks columns required to convert it."""

    def __init__(self, converter_type: str, missing: list[str]) -> None:
        self.converter_type = converter_type
        self.missing = missing
        super().__init__(
            f"Missing required column(s) for {converter_type}: {', '.join(missing)}"
        )


def get_requirement_sets(converter_type: str) -> tuple[set[str], set[str]]:
    """Return the (required, conditional) column sets for a converter type.

    "training" returns empty sets on purpose: its converter resolves the Event ID
    column via alias mapping (``TrainingConfig.COLUMN_MAPPING``) and already flags a
    missing one, so an exact-match hard-fail here would reject valid aliased uploads.
    """
    if converter_type == "counseling":
        return COUNSELING_REQUIRED, COUNSELING_CONDITIONAL
    if converter_type == "training-client":
        return TRAINING_CLIENT_REQUIRED, TRAINING_CLIENT_CONDITIONAL
    return set(), set()


def get_fabrication_defaults(converter_type: str) -> set[str]:
    """Columns whose absence makes the converter fabricate a non-empty default.

    Only the counseling converter does this with raw CSV columns. The training-client
    converter intentionally injects defaults for absent counseling columns
    (``TrainingClientConfig.DEFAULTS``), so it is excluded to avoid false warnings.
    """
    if converter_type == "counseling":
        return COUNSELING_FABRICATION_DEFAULTS
    return set()


def classify_columns(headers: list[str], converter_type: str) -> dict[str, list[str]]:
    """Classify a CSV's header set for a converter.

    Returns ``{"missing_required": [...], "missing_warn": [...]}`` where missing_warn
    is the union of missing conditional and missing fabrication-risk columns.
    """
    header_set = set(headers)
    required, conditional = get_requirement_sets(converter_type)
    fabrication = get_fabrication_defaults(converter_type)
    missing_required = sorted(required - header_set)
    missing_warn = sorted((conditional | fabrication) - header_set)
    return {"missing_required": missing_required, "missing_warn": missing_warn}


def read_header_row(path: str) -> list[str]:
    """Read just the header row of a CSV (utf-8-sig, matching the converters).

    Headers are whitespace-normalized (CONV-2) so required-column matching here
    agrees with the normalized keys the converters read. Duplicates are preserved
    so the caller can detect collisions (two columns collapsing to one name).
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f), [])
    return [normalize_header(h) for h in header]
