"""Characterization tests: pin current converter output byte-for-byte.

These assert *what the converters do today*, not what they ought to do. They
exist so the converter-layer refactor (findings 5.1/5.2 — dropping pandas,
introducing a column mapping, unifying the pipeline) can be verified as
genuinely behaviour-preserving rather than merely still-passing.

Two properties make this viable and necessary:

* Output is byte-deterministic — the generated XML carries no timestamps, so
  two runs over the same input produce identical bytes.
* The existing suite has real blind spots here. Nothing anywhere sets
  `progress_callback`, so the tick cadence is entirely untested; and the only
  multi-event fixture happens to use already-sorted event IDs, so nothing would
  notice that `DataFrame.groupby` sorts its keys while a dict does not.

Goldens are generated on first run and committed. When a change *should* move
the output, delete the affected golden, re-run, and review the diff — the point
is that the change is deliberate and visible, not that it never happens.
"""

import csv
import os
import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.converters.counseling_converter import CounselingConverter
from src.converters.training_client_converter import TrainingClientConverter
from src.converters.training_converter import TrainingConverter
from src.logging_util import ConversionLogger
from src.validation_report import ValidationTracker

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden"
SAMPLES = pathlib.Path(__file__).parent.parent / "apps" / "web" / "public" / "samples"

CONVERTERS = {
    "counseling": CounselingConverter,
    "training": TrainingConverter,
    "training-client": TrainingClientConverter,
}


def _convert(converter_type: str, rows: list[dict], fieldnames: list[str] | None = None) -> str:
    """Run a converter over `rows` and return the XML text."""
    logger = ConversionLogger(f"char_{converter_type}", log_to_file=False).logger
    validator = ValidationTracker()

    csv_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    )
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames or list(rows[0]))
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    csv_file.close()

    xml_path = tempfile.NamedTemporaryFile(suffix=".xml", delete=False).name
    try:
        CONVERTERS[converter_type](logger, validator).convert(csv_file.name, xml_path)
        return pathlib.Path(xml_path).read_text(encoding="utf-8")
    finally:
        os.unlink(csv_file.name)
        if os.path.exists(xml_path):
            os.unlink(xml_path)


def _convert_file(converter_type: str, csv_path: pathlib.Path) -> str:
    logger = ConversionLogger(f"char_{converter_type}", log_to_file=False).logger
    xml_path = tempfile.NamedTemporaryFile(suffix=".xml", delete=False).name
    try:
        CONVERTERS[converter_type](logger, ValidationTracker()).convert(str(csv_path), xml_path)
        return pathlib.Path(xml_path).read_text(encoding="utf-8")
    finally:
        if os.path.exists(xml_path):
            os.unlink(xml_path)


def _assert_matches_golden(name: str, actual: str) -> None:
    """Compare against the committed golden, creating it if absent."""
    GOLDEN_DIR.mkdir(exist_ok=True)
    golden = GOLDEN_DIR / f"{name}.xml"
    if not golden.exists():
        golden.write_text(actual, encoding="utf-8")
        pytest.skip(f"golden created: {golden.name} — re-run to assert against it")
    expected = golden.read_text(encoding="utf-8")
    assert actual == expected, (
        f"output for {name!r} changed.\n"
        f"If deliberate: delete tests/golden/{name}.xml, re-run, and review the diff."
    )


# --------------------------------------------------------------------------
# Shipped samples — the files the app links from its own landing page
# --------------------------------------------------------------------------

@pytest.mark.parametrize("converter_type", ["counseling", "training", "training-client"])
def test_shipped_sample_output_is_stable(converter_type):
    sample = SAMPLES / f"{converter_type}-sample.csv"
    assert sample.exists(), sample
    _assert_matches_golden(f"sample_{converter_type}", _convert_file(converter_type, sample))


@pytest.mark.parametrize("converter_type", ["counseling", "training", "training-client"])
def test_output_is_deterministic_across_runs(converter_type):
    """No timestamps or other run-varying content — the premise of this file."""
    sample = SAMPLES / f"{converter_type}-sample.csv"
    assert _convert_file(converter_type, sample) == _convert_file(converter_type, sample)


# --------------------------------------------------------------------------
# Edge fixtures — the cases the refactor is most likely to disturb
# --------------------------------------------------------------------------

def _counseling_row(**overrides):
    base = {
        "Contact ID": "C-001", "Last Name": "Smith", "First Name": "John",
        "Middle Name": "", "Email": "john@example.com",
        "Contact: Phone": "(515) 555-1234", "Contact: Secondary Phone": "",
        "Mailing Street": "123 Main St", "Mailing City": "Des Moines",
        "Mailing State/Province": "IA", "Mailing Zip/Postal Code": "50309",
        "Mailing Country": "US", "Agree to Impact Survey": "Yes",
        "Client Signature - Date": "2025-01-15", "Client Signature(On File)": "Yes",
        "Race": "White", "Ethnicity:": "Not Hispanic or Latino", "Gender": "Male",
        "Disability": "No", "Veteran Status": "No", "Currently In Business?": "No",
        "Type of Session": "Telephone", "Language(s) Used": "English",
        "Date": "2025-01-15", "Name of Counselor": "Jane Doe",
        "Duration (hours)": "1.5", "Prep Hours": "0.5", "Travel Hours": "0",
        "Services Provided": "Business Start-up/Preplanning",
        "Rural_vs_Urban": "Undetermined", "Activity ID": "A-001",
    }
    base.update(overrides)
    return base


def _training_row(**overrides):
    base = {
        "Class/Event ID": "EVT-001", "Class/Event Name": "Business Workshop",
        "Start Date": "2025-01-15", "Training Topic": "Technology",
        "Class/Event Type": "In-person", "City": "Des Moines",
        "State/Province": "Iowa", "Zip/Postal Code": "50309", "Gender": "Female",
        "Race": "White", "Ethnicity": "Non-Hispanic",
        "Veteran Status": "No military service", "Currently in Business?": "Yes",
        "Disabilities": "No",
    }
    base.update(overrides)
    return base


def test_training_event_order_is_stable_for_unsorted_input():
    """The single most likely silent regression when pandas goes.

    `DataFrame.groupby` defaults to sort=True, so records currently come out
    ordered by event ID regardless of file order. A `defaultdict` accumulation
    is insertion-ordered, which would reorder the XML with nothing to catch it —
    every other multi-event fixture in the suite uses already-sorted IDs.
    """
    rows = [
        _training_row(**{"Class/Event ID": "EVT-003", "Class/Event Name": "Third"}),
        _training_row(**{"Class/Event ID": "EVT-001", "Class/Event Name": "First"}),
        _training_row(**{"Class/Event ID": "EVT-002", "Class/Event Name": "Second"}),
        _training_row(**{"Class/Event ID": "EVT-001", "Gender": "Male"}),
    ]
    xml = _convert("training", rows)
    _assert_matches_golden("training_unsorted_event_ids", xml)

    # Stated explicitly so the intent survives even if the golden is regenerated.
    order = [
        line.split(">")[1].split("<")[0]
        for line in xml.splitlines()
        if "<PartnerTrainingNumber>" in line
    ]
    assert order == sorted(order), f"records must stay sorted by event id, got {order}"


def test_counseling_blank_optionals():
    """Every optional column blank — the empty-element bug class."""
    blanks = {
        k: "" for k in (
            "Email", "Middle Name", "Contact: Phone", "Contact: Secondary Phone",
            "Mailing Street", "Mailing City", "Mailing State/Province",
            "Mailing Zip/Postal Code", "Client Signature - Date",
            "Agree to Impact Survey", "Prep Hours", "Travel Hours",
            "Language(s) Used", "Disability", "Veteran Status", "Ethnicity:",
        )
    }
    _assert_matches_golden("counseling_blank_optionals", _convert("counseling", [_counseling_row(**blanks)]))


def test_counseling_multi_value_fields():
    """Semicolon-joined Salesforce multi-selects, incl. the maxOccurs=1 cap."""
    rows = [_counseling_row(**{
        "Currently In Business?": "Yes",
        "Race": "White;Asian",
        "Nature of the Counseling Seeking?": "Business Plan;eCommerce",
        "Services Provided": "Business Plan;Customer Relations",
        "Legal Entity of Business": "LLC",
    })]
    _assert_matches_golden("counseling_multi_value", _convert("counseling", rows))


def test_counseling_ragged_row():
    """A short row — DictReader yields None for the missing trailing fields."""
    full = _counseling_row()
    fieldnames = list(full)
    short = {k: full[k] for k in fieldnames[:6]}
    short["Contact ID"] = "C-002"
    _assert_matches_golden(
        "counseling_ragged_row", _convert("counseling", [full, short], fieldnames=fieldnames)
    )


def test_training_aliased_headers():
    """TrainingConfig.COLUMN_MAPPING alias resolution (list form)."""
    rows = [_training_row()]
    rows[0]["Address"] = rows[0].pop("City")  # 'Address' is a declared alias for city
    _assert_matches_golden("training_aliased_headers", _convert("training", rows))


def test_training_client_output_is_stable():
    rows = [{
        "Class/Event ID": "701Pe00000vtCVy", "Contact ID": "003Pe00000Sxsp4",
        "Member ID": "00vPe00000Pn89L", "First Name": "Jane", "Last Name": "Doe",
        "Member Type": "Contact", "Member Status": "Responded",
        "Company": "Doe Enterprises", "Phone": "5155551234",
        "Email": "jane@example.com", "Currently in Business?": "No",
        "Ethnicity": "Non Hispanic or Latino", "Race": "White", "Disabilities": "No",
        "Gender": "Female", "Military Status": "No military service",
        "Training Topic": "Marketing/Sales", "Class/Event Type": "In-Person",
        "Funding Source": "", "Class Teacher": "Mike Smith",
        "Street": "2210 Grand Ave", "city": "Des Moines", "State": "IA",
        "Zip code": "50312", "Start Date": "2025-04-08",
        "Class/Event Name": "Marketing Basics Workshop",
    }]
    _assert_matches_golden("training_client_basic", _convert("training-client", rows))


# --------------------------------------------------------------------------
# Progress callback — no coverage exists today
# --------------------------------------------------------------------------

def _ticks_for(converter_type: str, rows: list[dict]) -> list[tuple[int, int]]:
    logger = ConversionLogger("char_progress", log_to_file=False).logger
    converter = CONVERTERS[converter_type](logger, ValidationTracker())
    captured: list[tuple[int, int]] = []
    converter.progress_callback = lambda processed, total: captured.append((processed, total))

    csv_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    )
    writer = csv.DictWriter(csv_file, fieldnames=list(rows[0]))
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    csv_file.close()
    xml_path = tempfile.NamedTemporaryFile(suffix=".xml", delete=False).name
    try:
        converter.convert(csv_file.name, xml_path)
        return captured
    finally:
        os.unlink(csv_file.name)
        if os.path.exists(xml_path):
            os.unlink(xml_path)


def test_counseling_progress_brackets_the_run():
    rows = [_counseling_row(**{"Contact ID": f"C-{i:03d}"}) for i in range(1, 31)]
    ticks = _ticks_for("counseling", rows)
    assert ticks[0] == (0, 30), f"must anchor at zero, got {ticks[0]}"
    assert ticks[-1] == (30, 30), f"must land on 100%, got {ticks[-1]}"
    assert all(total == 30 for _, total in ticks)
    assert [p for p, _ in ticks] == sorted(p for p, _ in ticks)


def test_counseling_total_counts_rows_including_skipped():
    """`total` is len(rows), *before* validation drops any.

    Rows without a Contact ID are skipped but still tick, so the bar reaches
    100% even when nothing converts. Pinned because a shared pipeline could
    easily redefine `total` as "rows that will convert".
    """
    rows = [_counseling_row(), _counseling_row(**{"Contact ID": ""})]
    ticks = _ticks_for("counseling", rows)
    assert ticks[0] == (0, 2)
    assert ticks[-1] == (2, 2)


def test_training_progress_counts_event_groups_not_rows():
    """`total` is the number of events, not the number of CSV rows.

    Six rows across two events yields a two-unit bar. This differs from
    counseling and is user-visible, so a unified pipeline must not "fix" it.
    """
    rows = [_training_row(**{"Class/Event ID": f"EVT-{i % 2:03d}"}) for i in range(6)]
    ticks = _ticks_for("training", rows)
    assert ticks[0] == (0, 2), f"expected 2 event groups, got {ticks[0]}"
    assert ticks[-1] == (2, 2)


def test_progress_callback_failure_cannot_break_conversion():
    """The callback is best-effort: exceptions are swallowed by design."""
    logger = ConversionLogger("char_progress_boom", log_to_file=False).logger
    converter = CounselingConverter(logger, ValidationTracker())

    def boom(processed, total):
        raise RuntimeError("callback exploded")

    converter.progress_callback = boom
    csv_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    )
    row = _counseling_row()
    writer = csv.DictWriter(csv_file, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    csv_file.close()
    xml_path = tempfile.NamedTemporaryFile(suffix=".xml", delete=False).name
    try:
        converter.convert(csv_file.name, xml_path)  # must not raise
        assert "<CounselingRecord>" in pathlib.Path(xml_path).read_text(encoding="utf-8")
    finally:
        os.unlink(csv_file.name)
        if os.path.exists(xml_path):
            os.unlink(xml_path)
