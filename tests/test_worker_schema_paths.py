"""Tests for locating the bundled XSD schemas.

Deliberately does NOT monkeypatch SCHEMAS_DIR. Every other worker test patches
it to the real schemas directory, which is exactly why a broken default went
unnoticed: the default resolved to a path that does not exist in either the repo
or the Docker layout, and nothing failed loudly -- conversions reported
xsd_valid=false with an empty error list, and /validate-xsd returned the opaque
string "Validation error" for every document.
"""

import os

import pytest

pytest.importorskip("fastapi")

from app.core.paths import (
    REQUIRED_SCHEMA_FILES,
    XSD_MAP,
    default_schemas_dir,
    verify_schemas_dir,
)

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REAL_SCHEMAS = os.path.join(_REPO_ROOT, "schemas")


def test_default_resolves_to_the_real_schemas_directory():
    """The default -- with no SCHEMAS_DIR set -- must find the actual XSDs."""
    resolved = default_schemas_dir()
    assert os.path.isdir(resolved), resolved
    assert os.path.realpath(resolved) == os.path.realpath(_REAL_SCHEMAS)
    for name in REQUIRED_SCHEMA_FILES:
        assert os.path.exists(os.path.join(resolved, name)), name


@pytest.mark.parametrize(
    "module_path",
    [
        "app.services.conversion_service",
        "app.routes.validate",
        "app.routes.fix",
    ],
)
def test_every_consumer_resolves_to_a_usable_directory(module_path):
    """All three SCHEMAS_DIR bindings must point somewhere real.

    fix.py does `from .validate import SCHEMAS_DIR`, which is a separate binding
    from validate's own -- they are patched independently in the other tests, so
    they are checked independently here.
    """
    import importlib

    module = importlib.import_module(module_path)
    schemas_dir = module.SCHEMAS_DIR
    assert os.path.isdir(schemas_dir), f"{module_path}.SCHEMAS_DIR -> {schemas_dir}"
    for name in REQUIRED_SCHEMA_FILES:
        assert os.path.exists(os.path.join(schemas_dir, name)), f"{module_path}: {name}"


def test_every_xsd_map_target_exists():
    """Each converter type must map to a schema file that is actually present."""
    resolved = default_schemas_dir()
    for schema_type, filename in XSD_MAP.items():
        assert os.path.exists(os.path.join(resolved, filename)), f"{schema_type} -> {filename}"


def test_verify_accepts_the_real_directory():
    verify_schemas_dir(_REAL_SCHEMAS)  # must not raise


def test_verify_rejects_a_missing_directory(tmp_path):
    missing = str(tmp_path / "nope")
    with pytest.raises(RuntimeError, match="Schemas directory not found"):
        verify_schemas_dir(missing)


def test_verify_rejects_a_directory_missing_the_xsds(tmp_path):
    """An empty leftover directory must not pass as the schemas directory."""
    empty = tmp_path / "schemas"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="is missing"):
        verify_schemas_dir(str(empty))


def test_verify_rejects_a_partial_directory(tmp_path):
    partial = tmp_path / "schemas"
    partial.mkdir()
    (partial / REQUIRED_SCHEMA_FILES[0]).write_text("<xsd/>")
    with pytest.raises(RuntimeError, match=REQUIRED_SCHEMA_FILES[1]):
        verify_schemas_dir(str(partial))


def test_startup_fails_when_schemas_are_missing(monkeypatch, tmp_path):
    """The app must refuse to start rather than degrade silently."""
    import asyncio

    from app import main as worker_main
    from app.routes import validate as validate_route

    monkeypatch.setattr(validate_route, "SCHEMAS_DIR", str(tmp_path / "gone"))

    async def _run_lifespan():
        async with worker_main.lifespan(worker_main.app):
            pass

    with pytest.raises(RuntimeError, match="Schemas directory not found"):
        asyncio.run(_run_lifespan())


def test_startup_succeeds_with_real_schemas(monkeypatch):
    import asyncio

    from app import main as worker_main
    from app.routes import validate as validate_route

    monkeypatch.setattr(validate_route, "SCHEMAS_DIR", _REAL_SCHEMAS)

    async def _run_lifespan():
        async with worker_main.lifespan(worker_main.app):
            return True

    assert asyncio.run(_run_lifespan()) is True


def test_health_reports_schemas(monkeypatch):
    """/health surfaces the same condition for a running container."""
    import asyncio

    from app.routes import health as health_route
    from app.routes import validate as validate_route

    monkeypatch.setattr(validate_route, "SCHEMAS_DIR", _REAL_SCHEMAS)
    result = asyncio.run(health_route.health())
    assert result["checks"]["schemas"] == "ok"
    assert result["status"] == "ok"


def test_health_degrades_when_schemas_are_missing(monkeypatch, tmp_path):
    import asyncio

    from app.routes import health as health_route
    from app.routes import validate as validate_route

    monkeypatch.setattr(validate_route, "SCHEMAS_DIR", str(tmp_path / "gone"))
    result = asyncio.run(health_route.health())
    assert result["checks"]["schemas"] == "error"
    assert result["status"] == "degraded"


def test_health_ignores_an_absent_data_dir(monkeypatch, tmp_path):
    """DATA_DIR is informational only.

    Conversion payloads travel over HTTP, so the worker never reads or writes
    it; on a platform that mounts no volume, letting it degrade the status would
    fail the healthcheck of a perfectly functional worker.
    """
    import asyncio

    from app.routes import health as health_route
    from app.routes import validate as validate_route

    monkeypatch.setattr(validate_route, "SCHEMAS_DIR", _REAL_SCHEMAS)
    monkeypatch.setattr(health_route, "DATA_DIR", str(tmp_path / "no-volume-here"))
    result = asyncio.run(health_route.health())
    assert result["checks"]["data_dir"] == "unavailable"
    assert result["status"] == "ok"
