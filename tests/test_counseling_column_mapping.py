"""`CounselingConfig.COLUMN_MAPPING` is the single source for counseling headers.

The counseling header vocabulary used to be mirrored by hand in four places that
had already disagreed — `preview_service.COUNSELING_EXPECTED` (74 entries),
`xsd_error_mapping._COUNSELING_ELEMENT_FIELDS` (~90),
`diff_service.COUNSELING_CLEANING_MAP` (25) and the `column_requirements` tier
sets. Three columns had drifted to a spelling without the `(old)` suffix, and
because `_sanitize_column_mapping` allowlists rename targets by membership in the
expected list, the mapping page would offer — and accept — a rename that deleted
a column the converter needed.

`COUNSELING_EXPECTED` is now derived from the config. These tests pin the other
consumers to it, so a column can only be added or renamed in one place.
"""

import os
import sys

import pytest

pytest.importorskip("fastapi")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.column_requirements import COUNSELING_CONDITIONAL, COUNSELING_REQUIRED
from app.services.diff_service import COUNSELING_CLEANING_MAP
from app.services.preview_service import COUNSELING_EXPECTED, COUNSELING_FIELD_METADATA
from src.config import COUNSELING_FABRICATION_DEFAULTS, CounselingConfig
from src.xsd_error_mapping import _COUNSELING_ELEMENT_FIELDS


def _known() -> set[str]:
    return set(CounselingConfig.expected_columns())


def test_expected_columns_are_derived_from_the_config():
    assert COUNSELING_EXPECTED == CounselingConfig.expected_columns()


def test_expected_columns_have_no_duplicates():
    derived = CounselingConfig.expected_columns()
    assert len(derived) == len(set(derived))


def test_fallback_headers_are_all_expected_columns():
    """The trap that would silently reintroduce the original bug.

    Three of the Part 3 fallback headers ('Total Number of Employees',
    'Gross Revenues/Sales', 'Profits/Losses') are *also* read on their own as the
    intake snapshot, so unlike TrainingConfig.COLUMN_MAPPING a list here is not a
    set of aliases for one column. Deriving with `alts[0]` — which is what the
    training branch of get_expected_columns does — would drop them from the
    expected list, and the mapping page would then offer a rename that deletes a
    real column. That is exactly the failure this whole mapping exists to stop.
    """
    known = _known()
    for key, value in CounselingConfig.COLUMN_MAPPING.items():
        if isinstance(value, str):
            continue
        for header in value:
            assert header in known, (
                f"fallback header {header!r} for key {key!r} is missing from "
                "expected_columns(); it would be reported to the user as 'extra'"
            )


@pytest.mark.parametrize(
    ("label", "columns"),
    [
        (
            "xsd_error_mapping._COUNSELING_ELEMENT_FIELDS",
            {csv_col for _, csv_col in _COUNSELING_ELEMENT_FIELDS.values() if csv_col},
        ),
        (
            "diff_service.COUNSELING_CLEANING_MAP",
            {csv_col for csv_col, _, _ in COUNSELING_CLEANING_MAP},
        ),
        (
            "column_requirements.COUNSELING_REQUIRED/CONDITIONAL",
            COUNSELING_REQUIRED | COUNSELING_CONDITIONAL,
        ),
        (
            "preview_service.COUNSELING_FIELD_METADATA",
            set(COUNSELING_FIELD_METADATA),
        ),
        (
            "config.COUNSELING_FABRICATION_DEFAULTS",
            set(COUNSELING_FABRICATION_DEFAULTS),
        ),
    ],
)
def test_consumer_references_only_known_columns(label, columns):
    """Every structure keyed by a counseling CSV column agrees with the config.

    A column named here but absent from COLUMN_MAPPING is dead weight at best:
    the requirement tiers and field metadata are only ever looked up for expected
    columns, so a misspelled entry silently does nothing.
    """
    unknown = sorted(columns - _known())
    assert not unknown, f"{label} references columns not in COLUMN_MAPPING: {unknown}"


def test_headers_for_returns_fallback_order():
    assert CounselingConfig.headers_for("contact_id") == ["Contact ID"]
    assert CounselingConfig.headers_for("total_employees_part3") == [
        "Total No. of Employees (Meeting)",
        "Total Number of Employees",
    ]


def test_no_two_keys_declare_the_same_single_header():
    """Two keys pointing at one header would make renames ambiguous.

    Deliberately scoped to single-header (string) entries: the fallback lists
    reuse intake headers on purpose, which is the whole point of the fallback.
    """
    seen: dict[str, str] = {}
    for key, value in CounselingConfig.COLUMN_MAPPING.items():
        if not isinstance(value, str):
            continue
        assert value not in seen, (
            f"keys {seen[value]!r} and {key!r} both map to {value!r}"
        )
        seen[value] = key
