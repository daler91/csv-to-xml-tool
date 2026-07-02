"""Regression tests for training expected-column detection (Form 888 bug).

``get_expected_columns("training")`` must return the human CSV headers configured
in ``TrainingConfig.COLUMN_MAPPING`` (e.g. ``"Class/Event ID"``), NOT the internal
snake_case keys (``"event_id"``). Returning the key made ``read_csv_preview``
report the real ``Class/Event ID`` header as missing and fuzzy-suggest renaming it
to ``event_id``; the mapping page auto-applied that, the worker renamed the column
away, and the converter then failed with "Event ID column is missing."
"""

import pytest

pytest.importorskip("pandas")

from app.services.preview_service import get_expected_columns, read_csv_preview


def test_training_expected_columns_are_human_headers_not_keys():
    expected = get_expected_columns("training")
    # Canonical human headers (string-valued COLUMN_MAPPING entries) are present...
    for header in (
        "Class/Event ID",
        "Class/Event Name",
        "Start Date",
        "Funding Source",
        "Training Topic",
        "Class/Event Type",
    ):
        assert header in expected, f"{header!r} missing from {expected}"
    # ...and the internal snake_case keys are NOT.
    for key in ("event_id", "event_name", "start_date", "funding_source",
                "training_topic", "event_type"):
        assert key not in expected, f"internal key {key!r} leaked into {expected}"
    # List-valued entries still collapse to their first (canonical) alias.
    assert "City" in expected
    assert "State/Province" in expected


def test_training_preview_matches_class_event_id_with_no_bad_suggestion():
    csv = (
        "Class/Event ID,Class/Event Name,Start Date,Training Topic,Class/Event Type\n"
        "EVT-1,Workshop,2025-02-03,Marketing/Sales,In-person\n"
    )
    status = read_csv_preview(csv, "training")["column_status"]

    assert "Class/Event ID" in status["matched"]
    assert "Class/Event ID" not in status["missing"]
    assert "event_id" not in status["missing"]
    # No suggestion should rename the real header to the internal key.
    assert all(s["suggested_match"] != "event_id" for s in status["suggestions"])
    assert all(s["csv_column"] != "Class/Event ID" for s in status["suggestions"])
    # The Required badge resolves on the human header.
    assert status["field_requirements"].get("Class/Event ID") == "required"


# --- Feature 2.5: data_quality report in /preview ---
# read_csv_preview analyzes the FULL row set (not just the previewed rows) and
# returns {"total_rows", "checks"} where each check is {"key", "label",
# "count", "severity", "detail", "column"}; only count > 0 checks appear.


def _checks_by_key(result):
    return {c["key"]: c for c in result["data_quality"]["checks"]}


def test_counseling_data_quality_reports_expected_checks():
    csv = (
        "Contact ID,Last Name,Date,Gross Revenues/Sales\n"
        "C-1,Smith,2025-01-15,100\n"
        ",Jones,2025-01-15,\n"      # missing Contact ID -> row skipped entirely
        "C-3,Smith,03/04/2025,\n"   # ambiguous date + blank revenue cell
        "C-4,Brown,2025-01-15,\n"   # blank revenue cell
    )
    result = read_csv_preview(csv, "counseling")

    assert result["data_quality"]["total_rows"] == 4
    checks = _checks_by_key(result)

    missing_id = checks["missing_contact_id"]
    assert missing_id["count"] == 1
    assert missing_id["severity"] == "error"  # skipped rows, not just degraded
    assert missing_id["column"] == "Contact ID"
    assert "skipped" in missing_id["detail"]

    ambiguous = checks["ambiguous_date"]
    assert ambiguous["count"] == 1
    assert ambiguous["severity"] == "warning"
    assert ambiguous["column"] == "Date"
    assert "month-first" in ambiguous["detail"]

    revenue = checks["blank_gross_revenues_sales"]
    # 2 blank cells: the skipped row's blank cell never reaches the XML, so it
    # must not be counted (rows C-3 and C-4 only).
    assert revenue["count"] == 2
    assert revenue["severity"] == "warning"
    assert revenue["column"] == "Gross Revenues/Sales"
    assert "'0'" in revenue["detail"]  # names the substituted default

    # No other fabrication-risk columns are present in this CSV, so no other
    # blank_* checks may appear (absent columns are convert-time warnings).
    blank_keys = [k for k in checks if k.startswith("blank_")]
    assert blank_keys == ["blank_gross_revenues_sales"]


def test_counseling_data_quality_skips_absent_fabrication_columns():
    csv = (
        "Contact ID,Last Name,Date\n"
        "C-1,Smith,2025-01-15\n"
        "C-2,Jones,2025-01-15\n"
    )
    result = read_csv_preview(csv, "counseling")

    # 'Gross Revenues/Sales' (and every other fabrication-risk column) is
    # absent entirely -> no blank-cell check for it; clean file -> no checks.
    assert result["data_quality"] == {"total_rows": 2, "checks": []}


def test_counseling_data_quality_covers_rows_beyond_the_preview_window():
    # 25 data rows (> the 20-row preview window); the last one is missing its
    # Contact ID and must still be counted.
    rows = [f"C-{i},Smith,2025-01-15" for i in range(24)] + [",Smith,2025-01-15"]
    csv = "Contact ID,Last Name,Date\n" + "\n".join(rows) + "\n"
    result = read_csv_preview(csv, "counseling")

    assert len(result["rows"]) == 20
    assert result["data_quality"]["total_rows"] == 25
    assert _checks_by_key(result)["missing_contact_id"]["count"] == 1


def test_training_data_quality_checks():
    csv = (
        "Class/Event ID,Class/Event Name,Start Date\n"
        "EVT-1,Workshop,2025-02-03\n"
        ",Workshop,2025-02-03\n"   # missing event id -> row skipped
        "EVT-2,Workshop,not a date\n"
    )
    checks = _checks_by_key(read_csv_preview(csv, "training"))

    assert checks["missing_event_id"]["severity"] == "error"
    assert checks["missing_event_id"]["count"] == 1
    assert checks["missing_event_id"]["column"] == "Class/Event ID"
    # Unreadable Start Date converts but with the fabricated default date.
    assert checks["invalid_start_date"]["severity"] == "warning"
    assert checks["invalid_start_date"]["count"] == 1
    assert checks["invalid_start_date"]["column"] == "Start Date"


def test_training_client_data_quality_maps_columns_before_analysis():
    csv = (
        "Class/Event ID,Contact ID,Last Name,Start Date\n"
        "E-1,C-1,Smith,2025-01-15\n"
        ",C-2,,not a date\n"   # missing event id, missing last name, bad date
        "E-2,,Smith,2025-01-15\n"  # missing Contact ID -> row skipped
    )
    checks = _checks_by_key(read_csv_preview(csv, "training-client"))

    assert checks["missing_class_event_id"]["severity"] == "error"
    assert checks["missing_class_event_id"]["count"] == 1
    assert checks["missing_contact_id"]["severity"] == "error"
    assert checks["missing_contact_id"]["count"] == 1
    assert checks["missing_last_name"]["count"] == 1
    # The date check runs on the renamed column but reports the user's own
    # 'Start Date' header, not the internal 'Date' name.
    assert checks["invalid_date"]["column"] == "Start Date"
    assert "'Start Date'" in checks["invalid_date"]["label"]
    # The training-client form intentionally injects defaults for the
    # counseling fabrication-risk columns, so no blank_* checks appear.
    assert not any(k.startswith("blank_") for k in checks)
