"""The results page's before/after cleaning diff (apps/worker diff_service).

The second pass (2.6, 2.8) found it hid every value a cleaner dropped -- an
unreadable phone looked untouched -- and left out the enumeration mappers
entirely, while converters.md promised "every change is recorded".
"""

import csv
import os
import tempfile

import pytest

pytest.importorskip("fastapi")

from app.services.diff_service import generate_cleaning_diff  # noqa: E402


def _diff(rows, converter_type="counseling"):
    fieldnames = list(dict.fromkeys(k for row in rows for k in row))
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        path = f.name
    try:
        return {(d["field"], d["original"]): d for d in generate_cleaning_diff(path, converter_type)}
    finally:
        os.unlink(path)


def test_a_dropped_value_appears_with_an_empty_cleaned_value():
    diffs = _diff([{"Contact ID": "C-1", "Contact: Phone": "555-0101", "Gender": "Non-binary"}])
    assert diffs[("Contact: Phone", "555-0101")]["cleaned"] == ""
    assert diffs[("Gender", "Non-binary")]["cleaned"] == ""


def test_enumeration_mappers_are_in_the_diff():
    diffs = _diff([{
        "Contact ID": "C-1",
        "Ethnicity:": "Not Hispanic or Latino",
        "Veteran Status": "No",
        "Disability": "N",
        "Branch Of Service": "USMC",
        "Race": "Caucasian; Black",
        "Export Countries": "UK; Narnia",
    }])
    assert diffs[("Ethnicity:", "Not Hispanic or Latino")]["cleaned"] == "Non Hispanic or Latino"
    assert diffs[("Veteran Status", "No")]["cleaned"] == "No military service"
    assert diffs[("Disability", "N")]["cleaned"] == "No"
    assert diffs[("Branch Of Service", "USMC")]["cleaned"] == "Marine Corps"
    assert diffs[("Race", "Caucasian; Black")]["cleaned"] == "White; Black or African American"
    # Narnia is not on SBA's list: dropped from the XML, so from the "after" too.
    assert diffs[("Export Countries", "UK; Narnia")]["cleaned"] == "United Kingdom"


def test_values_the_converter_leaves_alone_are_not_reported():
    # A Salesforce trailing ';' on an already-valid multi-select is not a change.
    diffs = _diff([{"Contact ID": "C-1", "Race": "Black or African American; White;",
                    "Ethnicity:": "Hispanic or Latino", "Veteran Status": "Veteran"}])
    assert [key for key in diffs if key[0] in ("Race", "Ethnicity:", "Veteran Status")] == []


def test_counselor_notes_scrubbing_is_shown():
    diffs = _diff([{"Contact ID": "C-1", "Comments": "[User]: Met   with client"}])
    assert diffs[("Comments", "[User]: Met   with client")]["cleaned"] == "Met with client"


def test_training_client_columns_use_the_forms_own_names():
    diffs = _diff([{"Contact ID": "C-1", "Military Status": "Not Veteran", "Race": "Caucasian"}],
                  "training-client")
    assert diffs[("Military Status", "Not Veteran")]["cleaned"] == "No military service"
    assert diffs[("Race", "Caucasian")]["cleaned"] == "White"
