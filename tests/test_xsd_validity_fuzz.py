"""Generated CSVs must always convert to XML that passes SBA's XSDs.

The method of docs/reviews/XSD_VALIDITY_ANALYSIS.md, kept as a regression
test: a seeded generator fills every column a converter reads with the
schema's own values (exact, lower-cased, cut short, or joined into long
multi-selects), near misses and junk. Every file must validate, and the
converters' final XSD check must never have had to step in: the schema guard
and the converters are meant to handle each case themselves, leaving a row out
only for the values decision D1 covers.
"""

import csv
import io
import os
import tempfile
import unittest

from app.services.preview_service import get_expected_columns

from src.converters.base_converter import EmptyCSVError
from src.converters.counseling_converter import CounselingConverter
from src.converters.training_client_converter import TrainingClientConverter
from src.converters.training_converter import TrainingConverter
from src.logging_util import ConversionLogger
from src.schema_rules import load_rules, schema_path
from src.validation_report import ValidationTracker
from src.xml_validator import validate_against_xsd
from src.xsd_error_mapping import element_field_map

FILES = 12
ROWS_PER_FILE = 12

JUNK = [
    "", " ", "N/A", "none", "Yes", "NO", "Y", "true", "0", "-1", "12.5", "Other", "Unknown",
    "Prefer not to say", "José Muñoz–Peña", "<b>&amp;\"'</b>", "line1\nline2", "ctrl\x0bchar",
    "x" * 300, "A; B; C", ";", " ; ", "  padded  ", "\U0001F600 emoji", "﻿bom", "Ø" * 50,
]
KIND_POOLS = {
    "date": ["2025-01-15", "1/5/2025", "01/05/25", "13/01/2025", "02/30/2025", "Jan 5 2025",
             "2025-01-15T10:00:00", "9999-12-31", "12/31/1899", ""],
    "number": ["0", "1.5", "12.0", "-1", "(1,500)", "1,234.56", "$2,000", "1e5", "1E+21",
               "99999999999999999999999", "32768", "abc", " 7 ", "50%"],
    "email": ["john@example.com", "bad@", "a@b", "  JOHN@EXAMPLE.COM  ", "user@exa mple.com"],
    "phone": ["(515) 555-1234", "555-0101", "+1 515 555 1234", "1-800-FLOWERS", "25155551234"],
    "zip": ["50309", "50309-1234", "5030", "K1A 0B1", "50309-12345", "ABCDE"],
    "id": ["003XX000004TMM1AAA", "C-001", "C-001", "", "x" * 25, "  C-2  ", "ID<&>", "a" * 21],
    "location": ["123", "0", "abc", "12345678", "", "-5", "1.5"],
}
EVENT_IDS = ["EV1", "EV1 ", "EV-2", "003XX000004TMM1AAA", "E" * 25, "", "evt 3", "EV<4>"]
# The only values that may cost a row its place in the file (decision D1):
# identifiers over 20 characters, which are never cut, and a LocationCode
# that isn't a number SBA accepts. Anything else must be fixed or dropped.
MAY_LEAVE_A_ROW_OUT = {"Contact ID", "Activity ID", "Member ID", "Class/Event ID", "LocationCode"}


class _Lcg:
    """A 32-bit linear congruential generator (Numerical Recipes' constants),
    so every platform and Python version generates the same files."""

    def __init__(self, seed: int):
        self.state = seed

    def below(self, n: int) -> int:
        self.state = (1664525 * self.state + 1013904223) % 2**32
        return (self.state >> 8) % n

    def pick(self, values):
        return values[self.below(len(values))]


def _kind(column: str) -> str | None:
    name = column.lower()
    kinds = (
        ("date", ("date", "started")),
        ("email", ("email",)),
        ("phone", ("phone",)),
        ("zip", ("zip", "postal")),
        ("location", ("locationcode",)),
        ("id", ("contact id", "activity id", "member id")),
        ("number", ("hours", "duration", "employees", "revenue", "profit", "capital", "%")),
    )
    return next((kind for kind, words in kinds if any(w in name for w in words)), None)


def _enum_pools(schema_type: str) -> dict[str, list[str]]:
    """CSV column -> the XSD enumeration values of the element it feeds."""
    rules = load_rules(schema_path(schema_type))
    pools: dict[str, set] = {}
    for key, (_label, column) in element_field_map(schema_type).items():
        parts = tuple(key.split("/"))
        for path, rule in rules.items():
            if column and rule.enumeration and path[-len(parts):] == parts:
                pools.setdefault(column, set()).update(v for v in rule.enumeration if v)
    return {column: sorted(values) for column, values in pools.items()}


def _value(rng: _Lcg, column: str, pools: dict) -> str:
    roll = rng.below(100)
    if roll < 10:
        return ""
    values = pools.get(column)
    if values and roll < 65:
        shape = rng.below(4)
        if shape == 0:
            return rng.pick(values)
        if shape == 1:
            return rng.pick(values).lower()
        if shape == 2:
            count = rng.pick([2, 3, 15])
            return "; ".join(rng.pick(values) for _ in range(count)) + rng.pick(["", ";"])
        return rng.pick(values)[:3 + rng.below(10)]
    pool = KIND_POOLS.get(_kind(column))
    if pool and roll < 85:
        return rng.pick(pool)
    return rng.pick(JUNK)


class GeneratedInputTest(unittest.TestCase):

    def check(self, converter_class, schema_type, extra_columns=()):
        rng = _Lcg(sum(map(ord, schema_type)))
        columns = list(dict.fromkeys([*get_expected_columns(schema_type), *extra_columns]))
        pools = _enum_pools(schema_type)
        logger = ConversionLogger("test_xsd_validity_fuzz", log_to_file=False).logger
        tmp = tempfile.mkdtemp()
        converted = 0
        for number in range(FILES):
            rows = [{column: _value(rng, column, pools) for column in columns}
                    for _ in range(ROWS_PER_FILE)]
            if "Class/Event ID" in columns:
                for row in rows:
                    row["Class/Event ID"] = rng.pick(EVENT_IDS)
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
            csv_path = os.path.join(tmp, f"in_{number}.csv")
            xml_path = os.path.join(tmp, f"out_{number}.xml")
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                f.write(buffer.getvalue())

            tracker = ValidationTracker()
            try:
                converter_class(logger, tracker).convert(csv_path, xml_path)
            except EmptyCSVError:
                continue
            converted += 1
            with self.subTest(file=number):
                self.assertEqual(validate_against_xsd(xml_path, schema_path(schema_type))["errors"], [])
                caught_late = [i["message"] for i in tracker.issues
                               if "SBA's schema rejects this" in i["message"]]
                self.assertEqual(caught_late, [])
                left_out_for = {i["field_name"] for i in tracker.issues
                                if "record was left out" in i["message"]}
                self.assertLessEqual(left_out_for, MAY_LEAVE_A_ROW_OUT)
        # Most files have rows to convert; an all-skipped file proves nothing.
        self.assertGreater(converted, FILES // 2)

    def test_counseling(self):
        self.check(CounselingConverter, "counseling",
                   ("LocationCode", "FIPS_Code", "Rural_vs_Urban", "InternetUsage"))

    def test_training_client(self):
        self.check(TrainingClientConverter, "training-client")

    def test_training(self):
        self.check(TrainingConverter, "training", ("LocationCode",))


if __name__ == "__main__":
    unittest.main()
