"""run_conversion training-path regressions for the Form 888 mapping fix.

Covers:
- a ``Class/Event ID`` training CSV converts (the happy path the bug broke);
- the stale ``{"Class/Event ID": "event_id"}`` mapping (produced by the pre-fix
  auto-suggestion) is dropped by the safety net instead of breaking the job;
- a BOM-prefixed CSV with a real alias mapping still converts (utf-8-sig read);
- ``_sanitize_column_mapping`` keeps legitimate alias renames and drops bad ones.
"""

import os
import xml.etree.ElementTree as ET

from app.services import conversion_service
from app.services.conversion_service import run_conversion, _sanitize_column_mapping

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SCHEMAS_DIR = os.path.join(_REPO_ROOT, "schemas")

TRAINING_CSV = (
    "Class/Event ID,Class/Event Name,Start Date,Training Topic,Class/Event Type,"
    "Currently in Business?,Ethnicity,Race,Disabilities,Gender,Military Status,"
    "city,State,Zip code\n"
    "EVT-1,Always Ready: Marketing,2025-02-03,Marketing/Sales,In-person,Yes,"
    "Hispanic or Latino,White; ,No,Female,No military service,Des Moines,IA,50312\n"
    "EVT-1,Always Ready: Marketing,2025-02-03,Marketing/Sales,In-person,,"
    "Non Hispanic or Latino,Black or African American; ,No,Male,"
    "Service Disabled Veteran,Des Moines,IA,50312\n"
)


def _convert(tmp_path, csv_text, column_mapping=None):
    csv_path = os.path.join(str(tmp_path), "input.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(csv_text)
    xml_path = os.path.join(str(tmp_path), "out.xml")
    return run_conversion(
        csv_path=csv_path,
        xml_path=xml_path,
        converter_type="training",
        column_mapping=column_mapping,
    )


def test_sanitize_drops_stale_event_id_mapping_keeps_valid_alias():
    # The exact bad mapping the old fuzzy suggestion produced -> dropped, because
    # "event_id" is not a real expected (human-header) column.
    assert _sanitize_column_mapping({"Class/Event ID": "event_id"}, "training") == {}
    # A legitimate alias rename (target IS an expected header) -> kept.
    assert _sanitize_column_mapping(
        {"Partner Organization": "Cosponsor"}, "training"
    ) == {"Partner Organization": "Cosponsor"}
    # Unknown converter type: pass the mapping through unchanged (don't guess).
    assert _sanitize_column_mapping({"a": "b"}, "nonexistent") == {"a": "b"}


def test_training_csv_with_class_event_id_converts(tmp_path, monkeypatch):
    monkeypatch.setattr(conversion_service, "SCHEMAS_DIR", _SCHEMAS_DIR)
    result = _convert(tmp_path, TRAINING_CSV)
    assert result["stats"]["successful"] == 1
    assert result["stats"]["errors"] == 0
    root = ET.parse(result["xml_path"]).getroot()
    assert len(root.findall("ManagementTrainingRecord")) == 1


def test_stale_event_id_mapping_does_not_break_conversion(tmp_path, monkeypatch):
    # Reproduces the persisted-bad-mapping case: even with the stale entry, the
    # safety net drops it and the job still succeeds (no "Event ID is missing").
    monkeypatch.setattr(conversion_service, "SCHEMAS_DIR", _SCHEMAS_DIR)
    result = _convert(
        tmp_path, TRAINING_CSV, column_mapping={"Class/Event ID": "event_id"}
    )
    assert result["stats"]["successful"] == 1
    assert result["stats"]["errors"] == 0
    cats = [i["category"] for i in result["issues"]]
    assert "missing_required_field" not in cats


def test_bom_prefixed_training_csv_with_mapping_converts(tmp_path, monkeypatch):
    # utf-8-sig read (Edit 3): a BOM on the first header must not desync the
    # rename from the converter's read. Use a harmless real alias rename so the
    # mapping branch is exercised.
    monkeypatch.setattr(conversion_service, "SCHEMAS_DIR", _SCHEMAS_DIR)
    result = _convert(
        tmp_path, "﻿" + TRAINING_CSV, column_mapping={"city": "City"}
    )
    assert result["stats"]["successful"] == 1
    assert result["stats"]["errors"] == 0


def test_mapping_renames_a_header_with_stray_whitespace(tmp_path, monkeypatch):
    # The mapping page keys the mapping by the preview's normalized headers
    # ("Co-sponsor"); the file's own header has a trailing space. It used to be
    # renamed by its raw text, so it never was, and CosponsorsName vanished.
    monkeypatch.setattr(conversion_service, "SCHEMAS_DIR", _SCHEMAS_DIR)
    lines = TRAINING_CSV.splitlines()
    csv_text = "\n".join([lines[0] + ",Co-sponsor ", *(line + ",Iowa SBDC" for line in lines[1:])]) + "\n"
    result = _convert(tmp_path, csv_text, column_mapping={"Co-sponsor": "Cosponsor"})
    root = ET.parse(result["xml_path"]).getroot()
    assert root.findtext(".//CosponsorsName") == "Iowa SBDC"
    assert [i for i in result["issues"] if i["field_name"] == "Co-sponsor"] == []


def test_a_mapping_for_a_column_the_csv_lacks_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(conversion_service, "SCHEMAS_DIR", _SCHEMAS_DIR)
    result = _convert(tmp_path, TRAINING_CSV, column_mapping={"Partner Org": "Cosponsor"})
    warning, = [i for i in result["issues"] if i["field_name"] == "Partner Org"]
    assert "the CSV has no 'Partner Org' column" in warning["message"]


def test_a_windows_1252_csv_converts_with_or_without_a_mapping(tmp_path, monkeypatch):
    # The converter reads Windows-1252; run_conversion's own header reads were
    # strict UTF-8 and raised UnicodeDecodeError first.
    monkeypatch.setattr(conversion_service, "SCHEMAS_DIR", _SCHEMAS_DIR)
    csv_path = os.path.join(str(tmp_path), "input.csv")
    with open(csv_path, "wb") as f:
        f.write(TRAINING_CSV.replace("Always Ready: Marketing", "Taller – José Muñoz").encode("cp1252"))
    for mapping in (None, {"city": "City"}):
        result = run_conversion(csv_path, os.path.join(str(tmp_path), "out.xml"), "training",
                                column_mapping=mapping)
        root = ET.parse(result["xml_path"]).getroot()
        assert root.findtext(".//TrainingTitle") == "Taller – José Muñoz"
        assert [i for i in result["issues"] if "Windows-1252" in i["message"]], mapping
