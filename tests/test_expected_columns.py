"""The mapping page's expected-column list must match what the converter reads.

`preview_service.COUNSELING_EXPECTED` is a hand-maintained mirror of the header
literals in `CounselingConverter`, and it had silently drifted on three columns
(the converter reads `'8(a) Certified?(old)'`; the list said `'8(a) Certified?'`).

That is not cosmetic. The mapping page reports the user's real column as "extra"
and the never-read one as "missing"; `difflib.get_close_matches` (cutoff 0.6)
then suggests renaming the real column to the missing name; and
`conversion_service._sanitize_column_mapping` *accepts* that rename, because it
allowlists targets by membership in this very list. Accepting the suggestion
renamed away the column the converter needed.

Rather than hardcode the answer, the expected set is derived from the converter
source with `ast`, so the test stays true as the converter changes. This becomes
much simpler once the counseling headers move into config (finding 5.2) — at
that point both sides read the same mapping and this can assert on it directly.
"""

import ast
import os
import pathlib
import sys

import pytest

pytest.importorskip("fastapi")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.preview_service import COUNSELING_EXPECTED, get_expected_columns
from src.config import COUNSELING_FABRICATION_DEFAULTS, CounselingConfig

_CONVERTER = pathlib.Path(__file__).parent.parent / "src" / "converters" / "counseling_converter.py"


def _headers_read_by_converter() -> set[str]:
    """Every CSV header the counseling converter reads.

    Covers three access shapes:

    * ``row.get('Header', ...)`` — the bulk of them, still literals.
    * ``self._first_present(row, 'A', 'B', ...)`` — kept because the helper is
      still public API and callable with bare literals.
    * ``self._mapped(row, 'key')`` — resolved through
      ``CounselingConfig.COLUMN_MAPPING``. The four Part 3 impact fields are
      reachable *only* this way, so a scan that stopped at literals would report
      five real headers as unread and fail in the opposite direction.
    """
    tree = ast.parse(_CONVERTER.read_text())
    headers: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "get" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                headers.add(first.value)
        elif node.func.attr == "_first_present":
            for arg in node.args[1:]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    headers.add(arg.value)
        elif node.func.attr == "_mapped" and len(node.args) >= 2:
            key = node.args[1]
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                assert key.value in CounselingConfig.COLUMN_MAPPING, (
                    f"_mapped() called with {key.value!r}, which is not a "
                    "CounselingConfig.COLUMN_MAPPING key — it would raise at runtime"
                )
                headers.update(CounselingConfig.headers_for(key.value))
    return headers


def test_expected_columns_match_what_the_converter_reads():
    read = _headers_read_by_converter()
    expected = set(COUNSELING_EXPECTED)

    missing = read - expected
    stale = expected - read
    assert not missing, (
        "columns the converter reads but the mapping page doesn't expect — these "
        f"show as 'extra' to the user: {sorted(missing)}"
    )
    assert not stale, (
        "columns the mapping page expects but nothing reads — these show as "
        f"'missing' and are offered as rename targets: {sorted(stale)}"
    )


def test_expected_columns_have_no_duplicates():
    assert len(COUNSELING_EXPECTED) == len(set(COUNSELING_EXPECTED))


def test_fabrication_defaults_are_all_expected_columns():
    """A column that gets a fabricated default must be one the page knows about.

    Independent of the AST check above and catches two of the same three
    regressions — `COUNSELING_FABRICATION_DEFAULTS` in src/config.py had the
    correct "(old)" spellings all along, so the two lists disagreed with
    each other.
    """
    unknown = set(COUNSELING_FABRICATION_DEFAULTS) - set(COUNSELING_EXPECTED)
    assert not unknown, f"fabrication-default columns absent from COUNSELING_EXPECTED: {sorted(unknown)}"


def test_no_expected_column_is_a_near_duplicate_of_another():
    """Guards the specific shape of the bug: two spellings of one column.

    `X` and `X(old)` both being present would let the suggester map between
    them, which is how the rename-away happened.
    """
    normalized: dict[str, str] = {}
    for column in COUNSELING_EXPECTED:
        key = column.replace("(old)", "").strip().lower()
        assert key not in normalized, (
            f"{column!r} and {normalized[key]!r} differ only by the '(old)' suffix; "
            "the mapping page would offer a rename between them"
        )
        normalized[key] = column


def test_get_expected_columns_returns_the_same_list():
    assert set(get_expected_columns("counseling")) == set(COUNSELING_EXPECTED)
