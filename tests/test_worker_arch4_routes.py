"""Tests for the ARCH-4 path-handoff in the /convert and /preview routes.

The heavy converter is stubbed (we're testing the route's path wiring, not the
conversion itself): the route must read the input from the shared volume, write
output to the deterministic derived path, and return only the path — never file
content. A fakeredis client is injected so the ARCH-2 progress/cancel registry
clears don't reach for a real Redis.
"""

import asyncio
import os

import pytest
from fastapi import HTTPException

from app.core import security
from app.models.schemas import ConvertRequest, PreviewRequest
from app.routes import convert as convert_route
from app.routes import preview as preview_route


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    (d / "uploads").mkdir(parents=True)
    (d / "output").mkdir(parents=True)
    real = os.path.realpath(str(d))
    monkeypatch.setattr(security, "DATA_DIR", real)
    return real


@pytest.fixture(autouse=True)
def fake_redis():
    # The convert route clears the progress/cancel registries (ARCH-2), which
    # talk to Redis; inject an in-memory fake so the tests stay hermetic + fast.
    fakeredis = pytest.importorskip("fakeredis")
    from app.services import redis_client

    redis_client.set_client(fakeredis.FakeRedis(decode_responses=True))
    yield
    redis_client.set_client(None)


def _write_input(data_dir, job_id, file_name, content="Col\n1\n"):
    job_dir = os.path.join(data_dir, "uploads", job_id)
    os.makedirs(job_dir, exist_ok=True)
    path = os.path.join(job_dir, file_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def test_convert_reads_path_writes_derived_output_returns_path_only(
    data_dir, monkeypatch
):
    _write_input(data_dir, "jobA", "in.csv")
    captured = {}

    def fake_run_conversion(csv_path, xml_path, **kwargs):
        captured["csv_path"] = csv_path
        captured["xml_path"] = xml_path
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write("<root/>")  # simulate the converter writing the XML
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
        job_id="jobA", file_name="in.csv", converter_type="counseling"
    )
    result = asyncio.run(convert_route.convert(req))

    assert captured["csv_path"] == os.path.join(
        data_dir, "uploads", "jobA", "in.csv"
    )
    expected_out = os.path.join(data_dir, "output", "jobA", "jobA.xml")
    assert captured["xml_path"] == expected_out
    assert os.path.isfile(expected_out)  # worker wrote it to the shared volume
    assert result["xml_path"] == expected_out
    assert "xml_content" not in result  # no file content crosses HTTP


def test_convert_missing_input_returns_404(data_dir, monkeypatch):
    monkeypatch.setattr(convert_route, "run_conversion", lambda **k: {})
    req = ConvertRequest(
        job_id="ghost", file_name="in.csv", converter_type="counseling"
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(convert_route.convert(req))
    assert exc.value.status_code == 404


def test_convert_traversal_file_name_rejected(data_dir, monkeypatch):
    _write_input(data_dir, "jobA", "in.csv")
    monkeypatch.setattr(convert_route, "run_conversion", lambda **k: {})
    req = ConvertRequest(
        job_id="jobA", file_name="../../etc/passwd", converter_type="counseling"
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(convert_route.convert(req))
    assert exc.value.status_code in (400, 404)


def test_preview_reads_from_derived_path(data_dir, monkeypatch):
    _write_input(data_dir, "jobA", "in.csv")
    captured = {}

    def fake_read_csv_preview(csv_path, converter_type):
        captured["csv_path"] = csv_path
        return {
            "headers": ["Col"],
            "rows": [{"Col": "1"}],
            "total_rows": 1,
            "column_status": {},
        }

    monkeypatch.setattr(preview_route, "read_csv_preview", fake_read_csv_preview)

    req = PreviewRequest(
        job_id="jobA", file_name="in.csv", converter_type="counseling"
    )
    result = asyncio.run(preview_route.preview(req))

    assert captured["csv_path"] == os.path.join(
        data_dir, "uploads", "jobA", "in.csv"
    )
    assert result["total_rows"] == 1


def test_preview_missing_input_returns_404(data_dir, monkeypatch):
    monkeypatch.setattr(preview_route, "read_csv_preview", lambda *a, **k: {})
    req = PreviewRequest(
        job_id="ghost", file_name="in.csv", converter_type="counseling"
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(preview_route.preview(req))
    assert exc.value.status_code == 404
