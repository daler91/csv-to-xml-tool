"""Worker API surface and limits (third review pass C.4, D.2, D.3, D.4, D.5).

Each test pins a way the worker answered wrongly or without bounds: routes
missing from the startup log, 405s turned into 404s, a cancel or progress
answer that hid a Redis outage, a bogus converter type accepted, error bodies
in two shapes that echoed the request, and no limit on concurrent work or on
how long one conversion runs.
"""

import asyncio
import json
import unittest
from unittest import mock

import pytest

pytest.importorskip("fastapi")
fakeredis = pytest.importorskip("fakeredis")

from fastapi import HTTPException  # noqa: E402

from app import main as worker_main  # noqa: E402
from app.core import auth as worker_auth  # noqa: E402
from app.models.schemas import ConvertRequest  # noqa: E402
from app.routes import convert as convert_route  # noqa: E402
from app.services import redis_client  # noqa: E402

from tests.test_worker_availability import _StalledRedis  # noqa: E402
from tests.test_worker_content_routes import COUNSELING_CSV  # noqa: E402
from tests.test_worker_hardening import _asgi_request  # noqa: E402

TOKEN = "test-token"
AUTH = {"authorization": f"Bearer {TOKEN}"}


def _json_request(path, payload, method="POST", headers=None):
    body = json.dumps(payload).encode()
    all_headers = {"content-type": "application/json", "content-length": str(len(body)), **AUTH}
    all_headers.update(headers or {})
    status, raw = _asgi_request(worker_main.app, method, path, body, all_headers)
    return status, json.loads(raw) if raw else None


class _WorkerCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(worker_auth, "WORKER_AUTH_TOKEN", TOKEN)
        patcher.start()
        self.addCleanup(patcher.stop)
        redis_client.set_client(fakeredis.FakeRedis(decode_responses=True))
        self.addCleanup(redis_client.set_client, None)


class RouteTableTest(_WorkerCase):
    """D.3."""

    def test_startup_route_list_names_the_real_routes(self):
        # On FastAPI 0.141 included routers are _IncludedRouter entries
        # without `methods`; the old loop listed only the docs routes.
        for route in ("POST /convert", "POST /preview", "POST /validate-xsd",
                      "POST /fix-xml", "GET /convert/{job_id}/progress"):
            self.assertTrue(any(entry.endswith(route) for entry in worker_main._registered), route)

    def test_wrong_method_is_405_not_404(self):
        status, _ = _asgi_request(worker_main.app, "GET", "/convert", headers=AUTH)
        self.assertEqual(status, 405)

    def test_unknown_path_is_404_and_not_an_error_log(self):
        with self.assertLogs("app.main", level="INFO") as logs:
            status, body = _asgi_request(worker_main.app, "GET", "/wp-login.php")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["detail"], "No route matched")
        self.assertEqual([r for r in logs.records if r.levelname == "ERROR"], [])

    def test_route_level_404s_keep_their_own_detail(self):
        status, body = _json_request("/convert/job-x/progress", None, method="GET")
        self.assertEqual(status, 404)
        self.assertEqual(body["detail"], "No progress recorded for this job")


class RedisOutageAnswersTest(_WorkerCase):
    """D.2: Redis being down read as "cancelled" and as "no progress"."""

    def setUp(self):
        super().setUp()
        redis_client.set_client(_StalledRedis())

    def test_cancel_reports_the_signal_was_not_stored(self):
        status, body = _json_request("/convert/job-x/cancel", {})
        self.assertEqual(status, 503)
        self.assertNotIn("cancelled", body)

    def test_progress_is_unavailable_not_missing(self):
        status, _ = _json_request("/convert/job-x/progress", None, method="GET")
        self.assertEqual(status, 503)

    def test_cancel_still_succeeds_when_redis_is_up(self):
        redis_client.set_client(fakeredis.FakeRedis(decode_responses=True))
        status, body = _json_request("/convert/job-x/cancel", {})
        self.assertEqual((status, body["cancelled"]), (200, True))


class RequestValidationTest(_WorkerCase):
    """D.4 and D.5."""

    def test_preview_rejects_an_unknown_converter_type(self):
        status, body = _json_request(
            "/preview", {"job_id": "j", "csv_content": "a\n1\n", "converter_type": "bogus"})
        self.assertEqual(status, 422)
        self.assertIsInstance(body["detail"], str)
        self.assertIn("converter_type", body["detail"])

    def test_errors_are_strings_that_do_not_echo_input(self):
        status, body = _json_request(
            "/validate-xsd", {"job_id": "j", "xml_content": "<a/>", "schema_type": "<script>x"})
        self.assertEqual(status, 422)
        self.assertIsInstance(body["detail"], str)
        self.assertNotIn("<script>", json.dumps(body))

    def test_fix_xml_still_explains_an_unsupported_type(self):
        status, body = _json_request(
            "/fix-xml", {"job_id": "j", "xml_content": "<a/>", "schema_type": "training"})
        self.assertEqual(status, 400)
        self.assertEqual(body["detail"], "auto-fix supports counseling-format XML only")


class ConcurrencyLimitTest(unittest.TestCase):
    """C.4: no cap on how many heavy requests ran at once."""

    def setUp(self):
        patcher = mock.patch.object(worker_auth, "WORKER_AUTH_TOKEN", TOKEN)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, paths, headers=AUTH, limit=1):
        in_flight, peak = 0, 0

        async def inner(scope, receive, send):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1

        middleware = worker_main.ConcurrencyLimitMiddleware(inner)
        header_list = [(k.encode(), v.encode()) for k, v in headers.items()]

        async def main():
            await asyncio.gather(*(
                middleware({"type": "http", "path": path, "headers": header_list}, None, None)
                for path in paths))

        with mock.patch.object(worker_main, "MAX_CONCURRENT_REQUESTS", limit):
            asyncio.run(main())
        return peak

    def test_heavy_requests_wait_for_a_slot(self):
        self.assertEqual(self._run(["/convert"] * 4 + ["/preview"] * 2), 1)
        self.assertEqual(self._run(["/convert"] * 6, limit=3), 3)

    def test_light_and_unauthenticated_requests_are_not_queued(self):
        self.assertEqual(self._run(["/health", "/convert/j/progress", "/convert/j/cancel"]), 3)
        self.assertEqual(self._run(["/convert"] * 3, headers={"authorization": "Bearer nope"}), 3)


class ConversionDeadlineTest(_WorkerCase):
    """C.4: a conversion kept running after the web had given up on it."""

    def test_passing_the_deadline_is_a_504(self):
        req = ConvertRequest(job_id="jobDeadline", csv_content=COUNSELING_CSV,
                             converter_type="counseling")
        coroutine = convert_route.convert(req)
        with mock.patch.object(convert_route, "CONVERSION_DEADLINE_SECONDS", -1):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(coroutine)
        self.assertEqual(ctx.exception.status_code, 504)


if __name__ == "__main__":
    unittest.main()
