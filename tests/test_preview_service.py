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
