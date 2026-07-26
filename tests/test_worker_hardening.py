"""Tests for the worker's request-level security controls.

Covers the four findings in Tier 3 that live in the worker: a non-ASCII
Authorization header returning 500 instead of 401, a body-size cap that only
inspected Content-Length, unauthenticated disclosure of the route table and
OpenAPI schema, and an unsanitized job_id reaching the log format and Redis
keys.
"""

import json

import pytest

pytest.importorskip("fastapi")

from app.logging_context import job_id_var, set_job_id


def _asgi_request(app, method, path, body=b"", headers=None, chunks=None):
    """Drive an ASGI app directly.

    `chunks` sends the body as multiple http.request messages with no
    content-length header, which is how a chunked/streamed request arrives.
    """
    import asyncio

    header_list = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "headers": header_list,
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }

    if chunks is None:
        pending = [{"type": "http.request", "body": body, "more_body": False}]
    else:
        pending = [
            {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
            for i, c in enumerate(chunks)
        ]

    messages = []

    async def receive():
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    payload = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )
    return status, payload


@pytest.fixture
def worker_app(monkeypatch):
    from app import main as worker_main
    from app.core import auth as worker_auth

    monkeypatch.setattr(worker_auth, "WORKER_AUTH_TOKEN", "test-token")
    return worker_main.app


class TestAuthHeaderHandling:
    """secrets.compare_digest rejects str operands containing non-ASCII."""

    def _post(self, app, auth_header):
        payload = json.dumps(
            {"job_id": "j1", "xml_content": "<a/>", "schema_type": "counseling"}
        ).encode()
        headers = {
            "content-type": "application/json",
            "content-length": str(len(payload)),
        }
        if auth_header is not None:
            headers["authorization"] = auth_header
        return _asgi_request(app, "POST", "/validate-xsd", payload, headers)

    def test_missing_header_is_401(self, worker_app):
        status, _ = self._post(worker_app, None)
        assert status == 401

    def test_wrong_token_is_401(self, worker_app):
        status, _ = self._post(worker_app, "Bearer nope")
        assert status == 401

    def test_non_ascii_token_is_401_not_500(self, worker_app):
        """`Bearer café` used to raise inside the dependency and surface as 500."""
        status, _ = self._post(worker_app, "Bearer café")
        assert status == 401

    def test_non_ascii_is_rejected_even_matching_a_prefix(self, worker_app):
        status, _ = self._post(worker_app, "Bearer test-tokén")
        assert status == 401


class TestBodySizeCap:
    def test_oversized_declared_body_is_413(self, worker_app, monkeypatch):
        from app import main as worker_main

        monkeypatch.setattr(worker_main, "MAX_REQUEST_BYTES", 100)
        headers = {"content-type": "application/json", "content-length": "5000"}
        status, _ = _asgi_request(worker_app, "POST", "/validate-xsd", b"x", headers)
        assert status == 413

    def test_invalid_content_length_is_400(self, worker_app):
        headers = {"content-type": "application/json", "content-length": "abc"}
        status, _ = _asgi_request(worker_app, "POST", "/validate-xsd", b"x", headers)
        assert status == 400

    def test_undeclared_chunked_body_is_capped(self, worker_app, monkeypatch):
        """The cap used to be bypassable by omitting Content-Length.

        A chunked request skipped the check entirely and the whole body was
        buffered regardless of size.
        """
        from app import main as worker_main

        monkeypatch.setattr(worker_main, "MAX_REQUEST_BYTES", 64)
        chunks = [b"x" * 32, b"y" * 32, b"z" * 32]  # 96 bytes, no content-length
        status, _ = _asgi_request(
            worker_app,
            "POST",
            "/validate-xsd",
            headers={
                "content-type": "application/json",
                "authorization": "Bearer test-token",
            },
            chunks=chunks,
        )
        assert status == 413

    def test_small_chunked_body_passes_the_cap(self, worker_app, monkeypatch):
        """The streaming guard must not reject legitimate undeclared bodies."""
        from app import main as worker_main

        monkeypatch.setattr(worker_main, "MAX_REQUEST_BYTES", 10_000)
        payload = json.dumps(
            {"job_id": "j1", "xml_content": "<a/>", "schema_type": "counseling"}
        ).encode()
        status, _ = _asgi_request(
            worker_app,
            "POST",
            "/validate-xsd",
            headers={"content-type": "application/json"},
            chunks=[payload[:10], payload[10:]],
        )
        assert status == 401  # reached auth, i.e. was not size-rejected


class TestApiSurfaceDisclosure:
    def test_catch_all_hides_the_route_table_in_production(self, worker_app, monkeypatch):
        from app import main as worker_main

        monkeypatch.setattr(worker_main, "_DOCS_ENABLED", False)
        status, body = _asgi_request(worker_app, "GET", "/definitely-not-a-route")
        assert status == 404
        assert "registered_routes" not in json.loads(body)

    def test_catch_all_still_helps_in_development(self, worker_app, monkeypatch):
        from app import main as worker_main

        monkeypatch.setattr(worker_main, "_DOCS_ENABLED", True)
        status, body = _asgi_request(worker_app, "GET", "/definitely-not-a-route")
        assert status == 404
        assert "registered_routes" in json.loads(body)


class TestJobIdSanitization:
    def teardown_method(self):
        job_id_var.set("-")

    def test_strips_characters_that_forge_log_records(self):
        # LOG_FORMAT embeds the id as [%(job_id)s]; a newline lets a caller
        # write arbitrary lines into the log (CWE-117).
        assert set_job_id("abc\ndef ERROR fake") == "abcdefERRORfake"
        assert "\n" not in job_id_var.get()

    def test_strips_redis_key_metacharacters(self):
        assert set_job_id("*") == "-"
        assert set_job_id("a:b") == "ab"
        assert set_job_id("x\r\ny") == "xy"

    def test_truncates_absurd_ids(self):
        assert len(set_job_id("a" * 10_000)) == 64

    def test_preserves_real_job_ids(self):
        # The web issues cuids; sanitization must be a no-op for them.
        for real in ("clx1a2b3c4d5e6f7g8h9", "job_123-456", "cm5abcdef0000xyz"):
            assert set_job_id(real) == real

    def test_empty_becomes_the_placeholder(self):
        assert set_job_id("") == "-"
        assert set_job_id(None) == "-"
