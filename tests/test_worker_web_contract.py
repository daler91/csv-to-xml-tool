"""What the worker sends is what the web reads.

The web types the worker's JSON by hand (apps/web/src/types/index.ts and the
two XML-tool routes), while the worker returns plain dicts for everything
below the top level: stats, issues, cleaning diffs, XSD error details, the
preview's data-quality checks. Nothing linked the two. A key renamed on one
side would reach the results page as undefined -- an empty column, a missing
error, a row number of "undefined" -- with every test on both sides green.

These drive the real worker app in-process, as the web calls it, with input
that produces every nested shape, and check each response against the
TypeScript interfaces read from the web's source: every field the web
declares must be present (optional ones may be absent) with a value of the
declared primitive type, and every interface must actually have been checked.
"""

import asyncio
import json
import os
import re
import unittest

import pytest

pytest.importorskip("fastapi")
fakeredis = pytest.importorskip("fakeredis")

from app import main as worker_main
from app.core import auth as worker_auth
from app.services import redis_client


# TestCase assertions rather than bare asserts, which the code scanners report
# (Bandit B101); one instance serves every test.
check = unittest.TestCase()

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_WEB_SRC = os.path.join(_REPO_ROOT, "apps", "web", "src")
TS_SOURCES = [
    os.path.join(_WEB_SRC, "types", "index.ts"),
    os.path.join(_WEB_SRC, "app", "api", "validate-xml", "route.ts"),
    os.path.join(_WEB_SRC, "app", "api", "fix-xml", "route.ts"),
]

# A cell for each cleaning the diff shows (a state abbreviation, a US date, a
# formatted phone), a value SBA can't accept (the email), a row with no
# Contact ID for the data-quality report, and a misspelled header (Mailing Cty)
# for the preview to suggest renaming.
COUNSELING_CSV = (
    "Contact ID,Last Name,First Name,Email,Mailing State/Province,Mailing Zip/Postal Code,"
    "Contact: Phone,Race,Ethnicity:,Gender,Disability,Veteran Status,Currently In Business?,"
    "Type of Session,Language(s) Used,Date,Name of Counselor,Duration (hours),Mailing Cty\n"
    "C-001,Doe,Jane,jane@example.com,IA,50309,(515) 555-1234,White,Not Hispanic or Latino,"
    "Female,No,No,No,Telephone,English,1/14/2025,Pat Smith,1.5,Des Moines\n"
    "C-002,Roe,Rick,not-an-email,CA,90210,515.555.9999,Asian,Not Hispanic or Latino,"
    "Male,No,No,No,Telephone,English,1/15/2025,Pat Smith,1,Beverly Hills\n"
    ",Nobody,No,no@example.com,IA,50309,,White,Not Hispanic or Latino,"
    "Female,No,No,No,Telephone,English,1/16/2025,Pat Smith,1,Ames\n"
)


# --- the web's interfaces ----------------------------------------------------


def _parse_body(body):
    """{field: (optional, type)} for one interface body. A type is the
    TypeScript text, or ("object" | "array", {fields}) for an inline object
    type and an Array<{...}> of them."""
    root = {}
    stack = [root]
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith(("/*", "*", "//")):
            continue
        if line.startswith("}"):
            stack.pop()
            continue
        match = re.match(r"(\w+)(\?)?:\s*(.*?);?$", line)
        if not match:
            continue
        name, optional, ts_type = match.group(1), bool(match.group(2)), match.group(3)
        if ts_type.endswith("{"):
            fields = {}
            stack[-1][name] = (optional, ("array" if ts_type.startswith("Array<") else "object", fields))
            stack.append(fields)
        else:
            stack[-1][name] = (optional, ts_type)
    return root


def _interfaces():
    found = {}
    for path in TS_SOURCES:
        with open(path, encoding="utf-8") as f:
            source = f.read()
        for match in re.finditer(r"^(?:export )?interface (\w+) \{\n(.*?)^\}", source, re.M | re.S):
            found[match.group(1)] = _parse_body(match.group(2))
    return found


INTERFACES = _interfaces()


class _Checker:
    def __init__(self):
        self.problems = []
        self.checked = set()  # interfaces at least one value was checked against

    def interface(self, value, name, where):
        self.checked.add(name)
        self.fields(value, INTERFACES[name], f"{where} ({name})")

    def fields(self, value, fields, where):
        if not isinstance(value, dict):
            self.problems.append(f"{where}: expected an object, got {value!r:.60}")
            return
        for field, (optional, ts_type) in fields.items():
            if field not in value:
                if not optional:
                    self.problems.append(f"{where}: the web reads '{field}', the worker sends no such key")
                continue
            self.value(value[field], ts_type, f"{where}.{field}")

    def value(self, value, ts_type, where):
        if isinstance(ts_type, tuple):
            kind, fields = ts_type
            for item in (value if kind == "array" else [value]):
                self.fields(item, fields, where)
            return
        ts_type = ts_type.strip()
        if ts_type.endswith("[]") or ts_type.startswith("Array<"):
            inner = ts_type[:-2] if ts_type.endswith("[]") else ts_type[len("Array<"):-1]
            if not isinstance(value, list):
                self.problems.append(f"{where}: expected a list, got {value!r:.60}")
                return
            for index, item in enumerate(value):
                self.value(item, inner, f"{where}[{index}]")
        elif ts_type.startswith("Record<string, ") and ts_type.endswith(">"):
            if not isinstance(value, dict):
                self.problems.append(f"{where}: expected an object, got {value!r:.60}")
                return
            for key, item in value.items():
                self.value(item, ts_type[len("Record<string, "):-1], f"{where}[{key!r}]")
        elif ts_type in INTERFACES:
            self.interface(value, ts_type, where)
        elif not _primitive_matches(value, ts_type):
            self.problems.append(f"{where}: {value!r:.60} is not {ts_type}")


def _primitive_matches(value, ts_type):
    """For a union of primitives and string literals; any other type passes."""
    def one(part):
        if part == "string":
            return isinstance(value, str)
        if part == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if part == "boolean":
            return isinstance(value, bool)
        if part == "null":
            return value is None
        if re.fullmatch(r'"[^"]*"', part):
            return value == part[1:-1]
        return None  # a type this checker does not read

    results = [one(part.strip()) for part in ts_type.split("|")]
    return None in results or any(results)


# --- the worker, called as the web calls it ------------------------------------


@pytest.fixture(autouse=True)
def worker(monkeypatch):
    monkeypatch.setattr(worker_auth, "WORKER_AUTH_TOKEN", "contract-token")
    redis_client.set_client(fakeredis.FakeRedis(decode_responses=True))
    yield
    redis_client.set_client(None)


def _post(path, payload):
    body = json.dumps(payload).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        (b"authorization", b"Bearer contract-token"),
    ]
    messages = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "headers": headers, "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 80),
    }
    asyncio.run(worker_main.app(scope, receive, send))
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    check.assertEqual(status, 200, b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body"))
    return json.loads(b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body"))


def _broken(xml):
    """The converted XML with one value the counseling XSD rejects."""
    check.assertIn("<ZipCode>50309</ZipCode>", xml)
    return xml.replace("<ZipCode>50309</ZipCode>", "<ZipCode>5O309</ZipCode>", 1)


def test_the_web_has_the_interfaces_these_tests_read():
    for name in ("ConvertResponse", "ValidationIssue", "CleaningDiffEntry", "XsdErrorDetail",
                 "PreviewResponse", "DataQualityReport", "DataQualityCheck", "FieldDescription",
                 "ValidateXsdResponse", "FixXmlResponse"):
        check.assertTrue(INTERFACES.get(name), f"interface {name} not found in the web's source")


def test_every_response_has_the_shape_the_web_reads():
    checker = _Checker()

    converted = _post("/convert", {"job_id": "contract", "csv_content": COUNSELING_CSV,
                                   "converter_type": "counseling"})
    checker.interface(converted, "ConvertResponse", "/convert")

    preview = _post("/preview", {"job_id": "contract", "csv_content": COUNSELING_CSV,
                                 "converter_type": "counseling"})
    checker.interface(preview, "PreviewResponse", "/preview")

    broken = _broken(converted["xml_content"])
    validated = _post("/validate-xsd", {"job_id": "contract", "xml_content": broken,
                                        "schema_type": "counseling"})
    checker.interface(validated, "ValidateXsdResponse", "/validate-xsd")

    fixed = _post("/fix-xml", {"job_id": "contract", "xml_content": broken,
                               "schema_type": "counseling"})
    checker.interface(fixed, "FixXmlResponse", "/fix-xml")

    check.assertEqual(checker.problems, [])
    # Each nested shape must have been seen at least once, or an empty list
    # would let these pass while checking nothing.
    check.assertGreaterEqual(checker.checked, {
        "ConvertResponse", "ValidationIssue", "CleaningDiffEntry", "XsdErrorDetail",
        "PreviewResponse", "DataQualityReport", "DataQualityCheck", "FieldDescription",
        "ValidateXsdResponse", "FixXmlResponse",
    })
    # Inline element types are not in `checked`; these keep theirs non-empty.
    check.assertTrue(preview["column_status"]["suggestions"])
    check.assertTrue(validated["is_valid"] is False and validated["error_details"])
