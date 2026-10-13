"""Shared staging + validation helpers for the content-based XML tool
routes (/validate-xsd, /fix-xml).

Both routes receive XML text in the request body (web and worker are
separate services with no shared volume), stage it in a worker-local
temp dir, validate against an XSD, and map failures to structured
per-record details (feature 2.4). Only the fixing step differs, so the
common plumbing lives here. Routes keep their own module-level
SCHEMAS_DIR/XSD_MAP so tests can monkeypatch them per route.
"""

import asyncio
import os
import re
import shutil
import sys
import tempfile

# Ensure src is importable
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.xml_validator import validate_against_xsd
from src.xsd_error_mapping import build_error_details


# A JSON "\ud800" escape becomes a lone UTF-16 surrogate in a Python string;
# no UTF-8 text, and so no XML or CSV file, can hold one.
_LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")


def unpaired_surrogate_error(text: str, what: str) -> str | None:
    """Where `text` holds a lone surrogate, said for the user; None if it holds none.

    Staging such text raised UnicodeEncodeError: a 500 from /validate-xsd and
    /fix-xml, and "Invalid request parameters" from /convert. The web can't
    send one (TextDecoder never yields one); any other caller can.
    """
    match = _LONE_SURROGATE.search(text)
    if match is None:
        return None
    position = match.start()
    line = text.count("\n", 0, position) + 1
    column = position - text.rfind("\n", 0, position)
    return (f"The {what} holds an unpaired UTF-16 surrogate (U+{ord(match.group()):04X}) at line {line}, "
            f"column {column}: half of a character such as an emoji, which no {what} file can contain. "
            "Remove it and try again.")


def invalid_result(error: str, schema_type: str) -> dict:
    """validate_with_details' result for a document that never reached the
    validator, with the one detail Contract B gives each error."""
    return {
        "is_valid": False,
        "errors": [error],
        "error_count": 1,
        "error_details": build_error_details("", [error], schema_type),
    }


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


async def stage_xml_content(prefix: str, xml_content: str) -> tuple[str, str]:
    """Write xml_content into a fresh temp dir; returns (tmp_dir, xml_path).

    The caller owns cleanup — pair with ``cleanup_staging`` in a finally.
    """
    tmp_dir = await asyncio.to_thread(tempfile.mkdtemp, prefix=prefix)
    xml_path = os.path.join(tmp_dir, "input.xml")
    await asyncio.to_thread(write_text, xml_path, xml_content)
    return tmp_dir, xml_path


async def cleanup_staging(tmp_dir: str | None) -> None:
    if tmp_dir:
        await asyncio.to_thread(shutil.rmtree, tmp_dir, ignore_errors=True)


async def validate_with_details(
    xml_path: str, xsd_file: str, schema_type: str
) -> dict:
    """XSD-validate the staged file and build the Contract B error details.

    Malformed/unparseable XML is a *result* (is_valid=false with the parse
    error in errors), never an exception. Details degrade to null fields
    when an error can't be traced back to a record.
    """
    result = await asyncio.to_thread(validate_against_xsd, xml_path, xsd_file)
    errors = result.get("errors", [])
    is_valid = result.get("is_valid", False)
    error_details: list[dict] = []
    if not is_valid and errors:
        error_details = await asyncio.to_thread(
            build_error_details, xml_path, errors, schema_type
        )
    return {
        "is_valid": is_valid,
        "errors": errors,
        "error_count": len(errors),
        "error_details": error_details,
    }
