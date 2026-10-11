"""Worker availability under bad input and a degraded Redis (third pass C.2,
C.3, D.1, A.9).

Each test pins a way one request could take the worker -- or every other
request on it -- down: an entity declaration crashing /fix-xml, its CPU-bound
comparison stalling the event loop, a stalled Redis adding two seconds per
progress write, and an unreadable CSV answered with a retried 500.
"""

import asyncio
import os
import threading
import unittest
from unittest import mock

import pytest

pytest.importorskip("fastapi")
fakeredis = pytest.importorskip("fakeredis")

from fastapi import HTTPException  # noqa: E402

from app.models.schemas import ConvertRequest, FixXmlRequest, PreviewRequest  # noqa: E402
from app.routes import convert as convert_route  # noqa: E402
from app.routes import fix as fix_route  # noqa: E402
from app.routes import preview as preview_route  # noqa: E402
from app.services import redis_client  # noqa: E402
from app.services.cancellation import registry as cancel_registry  # noqa: E402
from app.services.progress import registry as progress_registry  # noqa: E402

_SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schemas")


# A quote opened and never closed: the csv module reads the rest of the file
# as one cell and gives up past its 131,072-character field limit.
def _unclosed_quote_csv():
    # Built on the content-route tests' counseling CSV so every required
    # column is present and the conversion gets as far as reading the rows.
    from tests.test_worker_content_routes import COUNSELING_CSV

    header, row = COUNSELING_CSV.splitlines()[:2]
    lines = [
        f"{header},Comments",
        f'{row},"' + "x" * 140_000,
        f"{row},fine",
    ]
    return "\n".join(lines) + "\n"


def _fix(xml_content):
    req = FixXmlRequest(job_id="jobAvail", xml_content=xml_content, schema_type="counseling")
    return asyncio.run(fix_route.fix_xml(req))


class FixXmlTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(fix_route, "SCHEMAS_DIR", _SCHEMAS_DIR)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_entity_declaration_is_a_result_not_a_500(self):
        """defusedxml refuses entity declarations with a ValueError, which
        escaped the fixer's ParseError handler and became a 500."""
        xml = '<!DOCTYPE x [<!ENTITY a "b">]><CounselingInformation>&a;</CounselingInformation>'

        result = _fix(xml)

        self.assertFalse(result["changed"])
        self.assertFalse(result["is_valid"])
        self.assertEqual(result["fixed_xml_content"], xml)

    def test_change_detection_runs_off_the_event_loop(self):
        """Two full parse/serialize passes -- about 10 s each on a 28 MB file --
        used to run on the event loop, stalling /health and every poll."""
        seen = []
        real_changed = fix_route._changed

        def recording_changed(original, fixed):
            seen.append(threading.current_thread() is threading.main_thread())
            return real_changed(original, fixed)

        with mock.patch.object(fix_route, "_changed", recording_changed):
            _fix("<CounselingInformation/>")

        self.assertEqual(seen, [False])


class _StalledRedis:
    """Every command fails as a stalled Redis does after its socket timeout."""

    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        def _timeout(*_args, **_kwargs):
            self.calls += 1
            raise TimeoutError("Timeout reading from socket")

        return _timeout


class RedisBreakerTest(unittest.TestCase):
    def setUp(self):
        self.stalled = _StalledRedis()
        redis_client.set_client(self.stalled)
        self.addCleanup(redis_client.set_client, None)

    def test_one_failure_stops_the_per_row_calls(self):
        """Each of these used to wait out the 2 s timeout: 600 rows took 68 s."""
        for processed in range(100):
            progress_registry.update("job1", processed, 100)
            self.assertFalse(cancel_registry.is_cancelled("job1"))

        self.assertEqual(self.stalled.calls, 1)
        self.assertIsNone(progress_registry.get("job1"))
        self.assertEqual(self.stalled.calls, 1)

    def test_calls_resume_once_the_breaker_window_passes(self):
        progress_registry.update("job1", 1, 2)
        self.assertEqual(self.stalled.calls, 1)

        healthy = fakeredis.FakeRedis(decode_responses=True)
        redis_client._client = healthy  # Redis recovered; breaker still open
        progress_registry.update("job1", 2, 2)
        self.assertIsNone(healthy.hgetall("csvxml:progress:job1") or None)

        with mock.patch.object(redis_client.time, "monotonic",
                               return_value=redis_client._open_until + 1):
            progress_registry.update("job1", 2, 2)
        self.assertEqual(healthy.hgetall("csvxml:progress:job1")["processed"], "2")


class UnreadableCsvTest(unittest.TestCase):
    def setUp(self):
        redis_client.set_client(fakeredis.FakeRedis(decode_responses=True))
        self.addCleanup(redis_client.set_client, None)

    def test_convert_answers_422_with_the_likely_cause(self):
        """A 500 was retried three times by the web and then shown as a generic
        failure; 422 is permanent there and its detail reaches the user."""
        req = ConvertRequest(job_id="jobQuote", csv_content=_unclosed_quote_csv(),
                             converter_type="counseling")
        coroutine = convert_route.convert(req)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(coroutine)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("quotation mark", ctx.exception.detail)

    def test_preview_answers_422_with_the_likely_cause(self):
        req = PreviewRequest(job_id="jobQuote", csv_content=_unclosed_quote_csv(),
                             converter_type="counseling")
        coroutine = preview_route.preview(req)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(coroutine)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("quotation mark", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
