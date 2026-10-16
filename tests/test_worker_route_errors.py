"""How the worker's routes answer a failure, and what they leave behind.

The status code is a contract with the web. Its job consumer drops a job the
worker answers 409 (the user cancelled), fails it at once on 400, 422 or 504
(retrying the same input cannot help), and retries anything else
(job-consumer.ts). The detail of a 400 or 422 is shown to the user
(worker-client.ts), so it has to say what to fix; a 500's must leak nothing.
And every route stages the request body in a worker-local temp dir that has to
go however the request ends.

test_worker_content_routes.py covers the success paths. These drive the failure
branches, with the step that does the work replaced by one that raises.
"""

import asyncio
import csv
import os

import pytest

pytest.importorskip("fastapi")
fakeredis = pytest.importorskip("fakeredis")

from fastapi import HTTPException

from app.models.schemas import (
    ConvertRequest,
    FixXmlRequest,
    PreviewRequest,
    ValidateXsdRequest,
)
from app.routes import convert as convert_route
from app.routes import fix as fix_route
from app.routes import preview as preview_route
from app.routes import validate as validate_route
from app.services import redis_client
from app.services.cancellation import ConversionCancelledError
from app.services.cancellation import registry as cancel_registry
from app.services.column_requirements import RequiredColumnsMissingError
from app.services.conversion_service import EmptyCSVError
from app.services.progress import registry as progress_registry

JOB_ID = "job-fails"

# The kind of thing an exception's text carries that must not reach a browser.
INTERNALS = "/srv/worker/tmp/convert_x1/input.csv: [Errno 28] No space left on device"


@pytest.fixture(autouse=True)
def fake_redis():
    # The convert route writes and clears the progress/cancel registries.
    redis_client.set_client(fakeredis.FakeRedis(decode_responses=True))
    yield
    redis_client.set_client(None)


def _raised(coroutine):
    """The HTTPException a route handler raised."""
    with pytest.raises(HTTPException) as exc:
        asyncio.run(coroutine)
    return exc.value


# --- /convert ---


def _convert_failing_with(monkeypatch, error):
    """Run /convert with a conversion that reports progress, then raises `error`.

    Returns the route's HTTPException and the staging dir it used.
    """
    seen = {}

    def run_conversion(csv_path, xml_path, on_progress, **kwargs):
        seen["staging_dir"] = os.path.dirname(csv_path)
        on_progress(5, 10)
        raise error

    monkeypatch.setattr(convert_route, "run_conversion", run_conversion)
    request = ConvertRequest(job_id=JOB_ID, csv_content="Col\n1\n", converter_type="counseling")
    return _raised(convert_route.convert(request)), seen["staging_dir"]


@pytest.mark.parametrize(
    "error, status",
    [
        pytest.param(ConversionCancelledError(), 409, id="cancelled"),
        pytest.param(convert_route.ConversionDeadlineError(), 504, id="past-the-deadline"),
        pytest.param(RequiredColumnsMissingError("counseling", ["Contact ID"]), 422, id="columns-missing"),
        pytest.param(EmptyCSVError("CSV has no data rows to convert."), 422, id="no-data-rows"),
        pytest.param(csv.Error("unexpected end of data"), 422, id="unparseable-csv"),
        pytest.param(ValueError(INTERNALS), 400, id="bad-value"),
        pytest.param(RuntimeError(INTERNALS), 500, id="worker-fault"),
    ],
)
def test_convert_answers_each_failure_with_the_status_the_web_acts_on(monkeypatch, error, status):
    raised, _ = _convert_failing_with(monkeypatch, error)
    assert raised.status_code == status


def test_convert_names_the_missing_columns_for_the_user(monkeypatch):
    raised, _ = _convert_failing_with(
        monkeypatch, RequiredColumnsMissingError("counseling", ["Contact ID", "Date"])
    )
    assert raised.status_code == 422
    assert "Contact ID" in raised.detail
    assert "Date" in raised.detail


@pytest.mark.parametrize(
    "error, status, detail",
    [
        (ValueError(INTERNALS), 400, "Invalid request parameters"),
        (RuntimeError(INTERNALS), 500, "Internal conversion error"),
    ],
    ids=["bad-value", "worker-fault"],
)
def test_convert_keeps_internals_out_of_a_generic_failure(monkeypatch, error, status, detail):
    raised, _ = _convert_failing_with(monkeypatch, error)
    assert (raised.status_code, raised.detail) == (status, detail)


@pytest.mark.parametrize(
    "error", [ConversionCancelledError(), RuntimeError(INTERNALS)], ids=["cancelled", "crashed"]
)
def test_a_failed_conversion_leaves_nothing_behind(monkeypatch, error):
    """A re-upload reuses the job id: it must start neither cancelled on
    arrival nor showing the dead attempt's progress. The route clears the
    progress snapshot on entry too, so the conversion writes one mid-run; the
    cancel flag is never cleared on entry, so only the exit can have done it."""
    cancel_registry.cancel(JOB_ID)

    _, staging_dir = _convert_failing_with(monkeypatch, error)

    assert not os.path.exists(staging_dir)
    assert progress_registry.get(JOB_ID) is None
    assert cancel_registry.is_cancelled(JOB_ID) is False


# --- /preview ---


def _preview_failing_with(monkeypatch, error):
    def read_csv_preview(csv_content, converter_type):
        raise error

    monkeypatch.setattr(preview_route, "read_csv_preview", read_csv_preview)
    request = PreviewRequest(job_id=JOB_ID, csv_content="Col\n1\n", converter_type="counseling")
    return _raised(preview_route.preview(request))


def test_preview_keeps_internals_out_of_a_worker_fault(monkeypatch):
    raised = _preview_failing_with(monkeypatch, RuntimeError(INTERNALS))
    assert (raised.status_code, raised.detail) == (500, "Internal preview error")


def test_preview_answers_a_bad_value_as_the_request_s_fault(monkeypatch):
    assert _preview_failing_with(monkeypatch, ValueError("bad value")).status_code == 400


# --- /validate-xsd and /fix-xml ---


def test_validate_refuses_an_unknown_schema_type_without_echoing_it():
    """schema_type is a Literal, so no HTTP request reaches this; a direct
    caller can, and error details never repeat request input."""
    request = ValidateXsdRequest.model_construct(
        job_id=JOB_ID, xml_content="<a/>", schema_type="<script>alert(1)</script>"
    )
    raised = _raised(validate_route.validate_xsd(request))
    assert (raised.status_code, raised.detail) == (400, "Unknown schema type")


def test_validate_keeps_internals_out_of_a_worker_fault_and_cleans_up(monkeypatch):
    seen = {}

    async def validate_with_details(xml_path, xsd_file, schema_type):
        seen["staging_dir"] = os.path.dirname(xml_path)
        raise RuntimeError(INTERNALS)

    monkeypatch.setattr(validate_route, "validate_with_details", validate_with_details)
    request = ValidateXsdRequest(job_id=JOB_ID, xml_content="<a/>", schema_type="counseling")

    raised = _raised(validate_route.validate_xsd(request))
    assert (raised.status_code, raised.detail) == (500, "Internal validation error")
    assert not os.path.exists(seen["staging_dir"])


def test_fix_keeps_internals_out_of_a_worker_fault_and_cleans_up(monkeypatch):
    seen = {}

    def fix_element_order(input_path, output_path, add_missing, xsd_file):
        seen["staging_dir"] = os.path.dirname(input_path)
        raise RuntimeError(INTERNALS)

    monkeypatch.setattr(fix_route, "fix_element_order", fix_element_order)
    request = FixXmlRequest(job_id=JOB_ID, xml_content="<a/>", schema_type="counseling")

    raised = _raised(fix_route.fix_xml(request))
    assert (raised.status_code, raised.detail) == (500, "Internal fix error")
    assert not os.path.exists(seen["staging_dir"])
