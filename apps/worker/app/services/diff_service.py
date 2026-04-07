"""Generates a cleaning diff by applying the same cleaning functions the converters
use and capturing before/after for every value that changes."""

import csv
import os
import sys

_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src import data_cleaning
from src.config import TrainingConfig

# (csv_column, cleaning_function, cleaning_type_label)
COUNSELING_CLEANING_MAP = [
    # Dates
    ("Client Signature - Date", data_cleaning.format_date, "format_date"),
    ("Date", data_cleaning.format_date, "format_date"),
    ("Reportable Impact Date", data_cleaning.format_date, "format_date"),
    ("Business Start Date", data_cleaning.format_date, "format_date"),
    ("Date Started (Meeting)", data_cleaning.format_date, "format_date"),
    # Phone
    ("Contact: Phone", data_cleaning.clean_phone_number, "clean_phone"),
    ("Contact: Secondary Phone", data_cleaning.clean_phone_number, "clean_phone"),
    # State / Country
    ("Mailing State/Province", data_cleaning.standardize_state_name, "standardize_state"),
    ("Mailing Country", data_cleaning.standardize_country_code, "standardize_country"),
    # Gender
    ("Gender", data_cleaning.map_gender_to_sex, "map_gender"),
    # Percentage
    ("Business Ownership - % Female(old)", data_cleaning.clean_percentage, "clean_percentage"),
    # Numeric
    ("Total Number of Employees", data_cleaning.clean_numeric, "clean_numeric"),
    ("Gross Revenues/Sales", data_cleaning.clean_numeric, "clean_numeric"),
    ("Profits/Losses", data_cleaning.clean_numeric, "clean_numeric"),
    ("SBA Loan Amount", data_cleaning.clean_numeric, "clean_numeric"),
    ("Non-SBA Loan Amount", data_cleaning.clean_numeric, "clean_numeric"),
    ("Amount of Equity Capital Received", data_cleaning.clean_numeric, "clean_numeric"),
    ("Duration (hours)", data_cleaning.clean_numeric, "clean_numeric"),
    ("Prep Hours", data_cleaning.clean_numeric, "clean_numeric"),
    ("Travel Hours", data_cleaning.clean_numeric, "clean_numeric"),
    ("Number of Employees in Exporting Business", data_cleaning.clean_numeric, "clean_numeric"),
    ("Gross Revenues/Sales (Meeting)", data_cleaning.clean_numeric, "clean_numeric"),
    ("Profit & Loss (Meeting)", data_cleaning.clean_numeric, "clean_numeric"),
    ("Total No. of Employees (Meeting)", data_cleaning.clean_numeric, "clean_numeric"),
]

_training_config = TrainingConfig()

TRAINING_CLEANING_MAP = [
    ("Start Date", data_cleaning.format_date, "format_date"),
]

# Add state columns from config (multiple possible column names)
_state_columns = _training_config.COLUMN_MAPPING.get("state", [])
if isinstance(_state_columns, str):
    _state_columns = [_state_columns]
for col in _state_columns:
    TRAINING_CLEANING_MAP.append((col, data_cleaning.standardize_state_name, "standardize_state"))

# Training client cleaning uses the training client CSV column names (before remapping)
TRAINING_CLIENT_CLEANING_MAP = [
    ("Start Date", data_cleaning.format_date, "format_date"),
    ("Phone", data_cleaning.clean_phone_number, "clean_phone"),
    ("State", data_cleaning.standardize_state_name, "standardize_state"),
    ("Gender", data_cleaning.map_gender_to_sex, "map_gender"),
]


def generate_cleaning_diff(
    csv_path: str,
    converter_type: str,
    column_mapping: dict[str, str] | None = None,
) -> list[dict]:
    """
    Read a CSV, apply the same cleaning functions the converters use,
    and return a list of diffs for every value that changed.

    Each entry: {row, record_id, field, original, cleaned, cleaning_type}
    """
    cleaning_maps = {
        "counseling": COUNSELING_CLEANING_MAP,
        "training": TRAINING_CLEANING_MAP,
        "training-client": TRAINING_CLIENT_CLEANING_MAP,
    }
    cleaning_map = cleaning_maps.get(converter_type, COUNSELING_CLEANING_MAP)

    # Build a reverse mapping so we can apply column renames
    rename = column_mapping or {}

    diffs: list[dict] = []

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row_index, row in enumerate(reader, 1):
            # Apply column mapping (rename keys)
            if rename:
                row = {rename.get(k, k): v for k, v in row.items()}

            record_id = (
                row.get("Contact ID", "") or
                row.get("Class/Event ID", "") or
                f"Row_{row_index}"
            )

            _diff_row(row, row_index, record_id, cleaning_map, diffs)

    return diffs


def _diff_row(
    row: dict,
    row_index: int,
    record_id: str,
    cleaning_map: list,
    diffs: list[dict],
) -> None:
    """Apply cleaning functions to a single row and append diffs."""
    for csv_col, func, cleaning_type in cleaning_map:
        original = row.get(csv_col, "")
        if not original or str(original).strip() == "" or str(original).lower() == "nan":
            continue

        original_str = str(original).strip()
        cleaned = str(func(original_str))

        if cleaned != original_str and cleaned != "":
            diffs.append({
                "row": row_index,
                "record_id": str(record_id),
                "field": csv_col,
                "original": original_str,
                "cleaned": cleaned,
                "cleaning_type": cleaning_type,
            })
