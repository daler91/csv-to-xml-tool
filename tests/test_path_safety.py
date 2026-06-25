"""Unit tests for the CLI path-confinement guard (src/path_safety.py).

These mirror tests/test_worker_path_resolution.py: the security-critical
property is that ``resolve_within`` confines a user-influenced path to an
allowed base and refuses anything that escapes it (a ``..`` sequence or an
absolute path pointing outside). Bases are passed explicitly so these do not
depend on the suite-wide ``SBA_OUTPUT_BASE`` set in conftest.py.
"""

import os

import pytest

from src.path_safety import output_base, resolve_within


def test_resolve_within_allows_relative_path(tmp_path):
    base = os.path.realpath(str(tmp_path))
    got = resolve_within(base, "reports/out.csv")
    assert got == os.path.join(base, "reports", "out.csv")


def test_resolve_within_allows_absolute_path_inside_base(tmp_path):
    base = str(tmp_path)
    inside = str(tmp_path / "sub" / "file.xml")
    assert resolve_within(base, inside) == os.path.realpath(inside)


def test_resolve_within_allows_base_itself(tmp_path):
    base = str(tmp_path)
    assert resolve_within(base, ".") == os.path.realpath(base)


def test_resolve_within_rejects_dotdot_escape(tmp_path):
    base = str(tmp_path / "base")
    os.makedirs(base)
    with pytest.raises(ValueError):
        resolve_within(base, "../escape.xml")


def test_resolve_within_rejects_absolute_outside_base(tmp_path):
    base = str(tmp_path / "base")
    os.makedirs(base)
    with pytest.raises(ValueError):
        resolve_within(base, "/etc/passwd")


def test_resolve_within_rejects_sibling_prefix(tmp_path):
    # A sibling like ``/data-evil`` must not count as inside ``/data`` -- the
    # ``base + os.sep`` suffix on the prefix check is what prevents that.
    base = str(tmp_path / "data")
    os.makedirs(base)
    sibling = str(tmp_path / "data-evil" / "x")
    with pytest.raises(ValueError):
        resolve_within(base, sibling)


def test_resolve_within_error_names_env_var(tmp_path):
    with pytest.raises(ValueError, match="SBA_OUTPUT_BASE"):
        resolve_within(str(tmp_path), "/etc/passwd")


def test_output_base_honors_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SBA_OUTPUT_BASE", str(tmp_path))
    assert output_base() == os.path.realpath(str(tmp_path))


def test_output_base_defaults_to_cwd(monkeypatch):
    monkeypatch.delenv("SBA_OUTPUT_BASE", raising=False)
    assert output_base() == os.path.realpath(os.getcwd())


def _close_handlers(logger):
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def test_logging_file_handler_confined(tmp_path, monkeypatch):
    """ConversionLogger creates its log dir/file under the confined base."""
    monkeypatch.setenv("SBA_OUTPUT_BASE", str(tmp_path))
    from src.logging_util import ConversionLogger

    log_dir = str(tmp_path / "logs")
    cl = ConversionLogger(logger_name="path_safety_cov", log_to_file=True, log_dir=log_dir)
    try:
        assert os.path.isdir(os.path.realpath(log_dir))
    finally:
        _close_handlers(cl.logger)


def test_logging_file_handler_rejects_escape(tmp_path, monkeypatch):
    """A log dir outside the base is refused before any handler is attached."""
    base = tmp_path / "base"
    base.mkdir()
    monkeypatch.setenv("SBA_OUTPUT_BASE", str(base))
    from src.logging_util import ConversionLogger

    with pytest.raises(ValueError):
        ConversionLogger(
            logger_name="path_safety_reject",
            log_to_file=True,
            log_dir=str(tmp_path / "outside"),
        )
