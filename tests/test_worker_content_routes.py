"""Tests for the content-passing contract in the /convert and /preview routes.

Web and worker are separate Railway services that cannot share a volume, so the
routes take the CSV text in the request body and return the XML text in the
response — never a shared-disk path. These tests prove that wiring; the
conversion itself is covered by the root converter suite. A fakeredis client is
injected so the progress/cancel registry clears stay hermetic.
"""

import asyncio
import os
import xml.etree.ElementTree as ET

import pytest

# fastapi (and the worker stack imported below) is a worker dependency; skip this
# module cleanly if it isn't installed rather than erroring at collection.
pytest.importorskip("fastapi")

from fastapi import HTTPException

from app.models.schemas import ConvertRequest, PreviewRequest
from app.routes import convert as convert_route
from app.routes import preview as preview_route

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SCHEMAS_DIR = os.path.join(_REPO_ROOT, "schemas")

# Per-attendee training rows using the real Salesforce vocabulary the converter
# fix handles: Prefer-not-to-say (excluded), multi-value Race, Service Disabled
# Veteran (counts as veteran too), and a non-enumerated Funding Source ("CORE").
TRAINING_CSV = (
    "Class/Event ID,Class/Event Name,Start Date,Training Topic,Class/Event Type,"
    "Funding Source,Currently in Business?,Ethnicity,Race,Disabilities,Gender,"
    "Military Status,city,State,Zip code\n"
    "EVT-1,Always Ready: Marketing,2025-02-03,Marketing/Sales,In-person,CORE,Yes,"
    "Hispanic or Latino,White; ,No,Female,No military service,Des Moines,IA,50312\n"
    "EVT-1,Always Ready: Marketing,2025-02-03,Marketing/Sales,In-person,CORE,,"
    "Non Hispanic or Latino,Asian; Black or African American; White; ,No,Male,"
    "Service Disabled Veteran,Des Moines,IA,50312\n"
    "EVT-1,Always Ready: Marketing,2025-02-03,Marketing/Sales,In-person,CORE,,"
    "Prefer not to say,Prefer not to say,,Prefer not to say,Prefer not to say,"
    "Des Moines,IA,50312\n"
)


@pytest.fixture(autouse=True)
def fake_redis():
    # The convert route clears the progress/cancel registries (ARCH-2), which talk
    # to Redis; inject an in-memory fake so the tests stay hermetic + fast.
    fakeredis = pytest.importorskip("fakeredis")
    from app.services import redis_client

    redis_client.set_client(fakeredis.FakeRedis(decode_responses=True))
    yield
    redis_client.set_client(None)


def test_convert_takes_content_and_returns_xml_content(monkeypatch):
    captured = {}

    def fake_run_conversion(csv_path, xml_path, **kwargs):
        # The route staged our csv_content at csv_path; the converter would read it.
        with open(csv_path, encoding="utf-8") as f:
            captured["csv_in"] = f.read()
        captured["xml_path"] = xml_path
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write("<root>ok</root>")  # simulate the converter writing the XML
        return {
            "xml_path": xml_path,
            "stats": {"total": 1, "successful": 1, "errors": 0, "warnings": 0},
            "xsd_valid": True,
            "xsd_errors": [],
            "issues": [],
            "cleaning_diff": [],
        }

    monkeypatch.setattr(convert_route, "run_conversion", fake_run_conversion)

    req = ConvertRequest(
        job_id="jobA", csv_content="Col\n1\n", converter_type="counseling"
    )
    result = asyncio.run(convert_route.convert(req))

    # CSV content is delivered to the converter; XML content comes back over HTTP;
    # no shared-disk path leaks out, and the worker-local temp dir is cleaned up.
    assert captured["csv_in"] == "Col\n1\n"
    assert result["xml_content"] == "<root>ok</root>"
    assert "xml_path" not in result
    assert not os.path.exists(captured["xml_path"])


def test_preview_takes_content_not_a_path(monkeypatch):
    captured = {}

    def fake_read_csv_preview(csv_content, converter_type):
        captured["csv_content"] = csv_content
        return {
            "headers": ["Col"],
            "rows": [{"Col": "1"}],
            "total_rows": 1,
            "column_status": {},
        }

    monkeypatch.setattr(preview_route, "read_csv_preview", fake_read_csv_preview)

    req = PreviewRequest(
        job_id="jobA", csv_content="Col\n1\n", converter_type="counseling"
    )
    result = asyncio.run(preview_route.preview(req))

    assert captured["csv_content"] == "Col\n1\n"
    assert result["total_rows"] == 1


def test_convert_empty_csv_maps_to_422(monkeypatch):
    # CONV-6: the converter raises EmptyCSVError for a headers-only CSV; the route
    # must surface it as 422 (before the generic ValueError -> 400 handler).
    from app.services.conversion_service import EmptyCSVError

    def _raise_empty(*args, **kwargs):
        raise EmptyCSVError("CSV has no data rows to convert.")

    monkeypatch.setattr(convert_route, "run_conversion", _raise_empty)
    req = ConvertRequest(
        job_id="jobE", csv_content="Col\n", converter_type="counseling"
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(convert_route.convert(req))
    assert exc.value.status_code == 422


def test_convert_end_to_end_content_to_valid_xml(monkeypatch):
    """Real conversion through the route: CSV text in -> XSD-valid XML text out,
    with the corrected per-attendee demographic aggregation."""
    from app.services import conversion_service

    monkeypatch.setattr(conversion_service, "SCHEMAS_DIR", _SCHEMAS_DIR)

    req = ConvertRequest(
        job_id="jobT", csv_content=TRAINING_CSV, converter_type="training"
    )
    result = asyncio.run(convert_route.convert(req))

    assert result["xsd_valid"] is True, result["xsd_errors"]
    root = ET.fromstring(result["xml_content"])
    records = root.findall("ManagementTrainingRecord")
    assert len(records) == 1
    nt = records[0].find("NumberTrained")
    assert nt.find("Total").text == "3"
    assert nt.find("Female").text == "1"  # "Prefer not to say" excluded
    assert nt.find("Male").text == "1"
    assert nt.find("Veterans").text == "1"
    assert nt.find("ServiceDisabledVeterans").text == "1"
    assert records[0].find("FundingSource") is None  # CORE omitted -> stays valid


def test_convert_ignores_stale_event_id_mapping(monkeypatch):
    """A persisted {"Class/Event ID": "event_id"} mapping (the pre-fix auto-
    suggestion) must not break /convert: the worker drops the invalid target and
    still converts the file instead of failing with "Event ID column is missing.\""""
    from app.services import conversion_service

    monkeypatch.setattr(conversion_service, "SCHEMAS_DIR", _SCHEMAS_DIR)
    req = ConvertRequest(
        job_id="jobStale",
        csv_content=TRAINING_CSV,
        converter_type="training",
        column_mapping={"Class/Event ID": "event_id"},
    )
    result = asyncio.run(convert_route.convert(req))

    assert result["stats"]["successful"] == 1
    assert result["stats"]["errors"] == 0
    cats = [i["category"] for i in result["issues"]]
    assert "missing_required_field" not in cats
    root = ET.fromstring(result["xml_content"])
    assert len(root.findall("ManagementTrainingRecord")) == 1
