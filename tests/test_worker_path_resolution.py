"""Tests for the ARCH-4 shared-volume path resolution helpers.

``resolve_input_csv`` / ``resolve_output_xml`` replace the old stream-the-file-
over-HTTP path with deriving paths under DATA_DIR, so the security-critical part
is that they confine everything to DATA_DIR and never point outside it.
"""

import os

import pytest

from app.core import security


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    (d / "uploads").mkdir(parents=True)
    (d / "output").mkdir(parents=True)
    real = os.path.realpath(str(d))
    monkeypatch.setattr(security, "DATA_DIR", real)
    return real


def _write_upload(data_dir, job_id, file_name, content="Col\n1\n"):
    job_dir = os.path.join(data_dir, "uploads", job_id)
    os.makedirs(job_dir, exist_ok=True)
    path = os.path.join(job_dir, file_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def test_resolve_input_csv_happy_path(data_dir):
    expected = _write_upload(data_dir, "job123", "data.csv")
    got = security.resolve_input_csv("job123", "data.csv")
    assert got == os.path.realpath(expected)
    assert got.startswith(data_dir + os.sep)


def test_resolve_input_csv_allows_leading_dot_filename(data_dir):
    # The web's upload sanitizer keeps leading-dot names, so resolution must too.
    # (It validates by existence + prefix, not by re-running sanitize_filename,
    # which would reject a leading dot and miss a file the web actually wrote.)
    expected = _write_upload(data_dir, "job123", ".hidden.csv")
    got = security.resolve_input_csv("job123", ".hidden.csv")
    assert got == os.path.realpath(expected)


def test_resolve_input_csv_missing_file_raises_not_found(data_dir):
    with pytest.raises(FileNotFoundError):
        security.resolve_input_csv("job123", "nope.csv")


def test_resolve_input_csv_basenames_directory_in_file_name(data_dir):
    # A file_name carrying path segments is reduced to its basename, so the
    # lookup stays in uploads/{job}/ and can't escape; the basename won't exist.
    _write_upload(data_dir, "job123", "data.csv")
    with pytest.raises(FileNotFoundError):
        security.resolve_input_csv("job123", "../../etc/passwd")


def test_resolve_input_csv_rejects_dotdot_leaf(data_dir):
    # basename("..") == ".." -> resolves to uploads/ (a dir) -> isfile() False.
    with pytest.raises(FileNotFoundError):
        security.resolve_input_csv("job123", "..")


def test_resolve_input_csv_sanitizes_job_id(data_dir):
    # job_id is stripped to [a-zA-Z0-9_-]; a traversal id can't reach outside.
    with pytest.raises((FileNotFoundError, ValueError)):
        security.resolve_input_csv("../../etc", "passwd")


def test_resolve_output_xml_is_deterministic(data_dir):
    got = security.resolve_output_xml("job123")
    assert got == os.path.join(data_dir, "output", "job123", "job123.xml")
    assert got.startswith(data_dir + os.sep)


def test_resolve_output_xml_sanitizes_job_id(data_dir):
    # Slashes/dots stripped from the id; the path stays under DATA_DIR/output.
    got = security.resolve_output_xml("job/../123")
    assert got == os.path.join(data_dir, "output", "job123", "job123.xml")
