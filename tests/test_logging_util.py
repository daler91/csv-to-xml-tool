"""Tests for src/logging_util.ConversionLogger.

Every CLI run builds one of these. What matters about it: the log file is
confined to SBA_OUTPUT_BASE like every other CLI write (CWE-22), rebuilding a
logger in the same process doesn't print every line twice, the file rotates
rather than growing without bound (QUAL-5), and importing the module touches
neither the logging configuration nor the disk.
"""

import ast
import logging
import os
import re
import unittest
import uuid
from logging.handlers import RotatingFileHandler

import pytest

import src.logging_util
from src.logging_util import ConversionLogger


# TestCase assertions rather than bare asserts, which the code scanners report
# (Bandit B101); one instance serves every test.
check = unittest.TestCase()


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Confine CLI writes to a fresh directory, as each CLI does via SBA_OUTPUT_BASE."""
    monkeypatch.setenv("SBA_OUTPUT_BASE", str(tmp_path))
    return tmp_path


@pytest.fixture
def make_logger():
    """Build ConversionLoggers under fresh names; close their files afterwards."""
    names = []

    def make(**kwargs):
        names.append(kwargs.setdefault("logger_name", f"test_logging_util_{uuid.uuid4().hex[:8]}"))
        return ConversionLogger(**kwargs)

    yield make
    for name in names:
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            handler.close()
        logger.handlers = []


def _file_handlers(conversion_logger):
    return [h for h in conversion_logger.logger.handlers if isinstance(h, RotatingFileHandler)]


class TestWhereItLogs:
    def test_console_only_when_file_logging_is_off(self, base, make_logger):
        log = make_logger(log_to_file=False)
        check.assertEqual(len(log.logger.handlers), 1)
        check.assertFalse(_file_handlers(log))
        check.assertEqual(list(base.iterdir()), [])

    def test_a_timestamped_file_under_log_dir_by_default(self, base, make_logger):
        log = make_logger(log_dir="logs")
        log.info("first record")

        [handler] = _file_handlers(log)
        path = handler.baseFilename
        check.assertEqual(os.path.dirname(path), os.path.realpath(base / "logs"))
        check.assertTrue(re.fullmatch(rf"{log.logger.name}_\d{{8}}_\d{{6}}\.log", os.path.basename(path)))
        with open(path, encoding="utf-8") as f:
            content = f.read()
        check.assertIn("Logging to file:", content)
        check.assertIn("first record", content)

    def test_an_explicit_log_file_path_gets_its_directory_created(self, base, make_logger):
        log = make_logger(log_file_path=os.path.join("nested", "deeper", "run.log"))
        log.info("first record")
        check.assertIn("first record", (base / "nested" / "deeper" / "run.log").read_text(encoding="utf-8"))

    def test_an_explicit_log_file_path_logs_to_file_even_with_file_logging_off(self, base, make_logger):
        log = make_logger(log_to_file=False, log_file_path="run.log")
        check.assertEqual(len(_file_handlers(log)), 1)
        check.assertTrue((base / "run.log").is_file())


class TestConfinement:
    """A stray --log-dir or log path must not write outside SBA_OUTPUT_BASE."""

    @pytest.mark.parametrize(
        "kwargs, escaped",
        [
            ({"log_dir": os.path.join("..", "escaped-logs")}, "escaped-logs"),
            ({"log_file_path": os.path.join("..", "escaped.log")}, "escaped.log"),
        ],
        ids=["log_dir", "log_file_path"],
    )
    def test_a_relative_escape_is_refused_before_anything_is_written(
        self, base, make_logger, kwargs, escaped
    ):
        with pytest.raises(ValueError, match="SBA_OUTPUT_BASE"):
            make_logger(**kwargs)
        check.assertFalse((base.parent / escaped).exists())

    def test_an_absolute_path_outside_the_base_is_refused(self, base, make_logger, tmp_path_factory):
        outside = tmp_path_factory.mktemp("outside")
        with pytest.raises(ValueError, match="SBA_OUTPUT_BASE"):
            make_logger(log_file_path=str(outside / "run.log"))
        check.assertEqual(list(outside.iterdir()), [])


class TestMessages:
    def test_rebuilding_a_logger_does_not_print_every_line_twice(self, base, make_logger, capsys):
        name = f"test_logging_util_{uuid.uuid4().hex[:8]}"
        make_logger(logger_name=name, log_to_file=False)
        rebuilt = make_logger(logger_name=name, log_to_file=False)

        rebuilt.info("said once")
        check.assertEqual(len(rebuilt.logger.handlers), 1)
        check.assertEqual(capsys.readouterr().err.count("said once"), 1)

    def test_warnings_and_errors_name_the_record_when_given_one(self, base, make_logger, caplog):
        log = make_logger(log_to_file=False)
        with caplog.at_level(logging.WARNING, logger=log.logger.name):
            log.warning("bad ZIP", record_id="003XX01")
            log.error("no session date", record_id="003XX02")
            log.warning("file-level warning")
            log.error("file-level error")

        check.assertEqual([(r.levelno, r.getMessage()) for r in caplog.records], [
            (logging.WARNING, "[Record 003XX01] bad ZIP"),
            (logging.ERROR, "[Record 003XX02] no session date"),
            (logging.WARNING, "file-level warning"),
            (logging.ERROR, "file-level error"),
        ])

    def test_debug_lines_appear_only_at_debug_level(self, base, make_logger, caplog):
        default = make_logger(log_to_file=False)
        verbose = make_logger(log_to_file=False, log_level=logging.DEBUG)
        with caplog.at_level(logging.DEBUG):
            default.debug("dropped at INFO")
            verbose.debug("kept at DEBUG")

        messages = [r.getMessage() for r in caplog.records]
        check.assertIn("kept at DEBUG", messages)
        check.assertNotIn("dropped at INFO", messages)


class TestRotation:
    def test_the_file_rotates_and_keeps_only_backup_count_old_files(self, base, make_logger):
        log = make_logger(log_file_path="run.log", max_bytes=512, backup_count=2)
        for line in range(60):
            log.info(f"line {line:02d} " + "x" * 80)

        check.assertEqual(sorted(p.name for p in base.iterdir()), ["run.log", "run.log.1", "run.log.2"])
        check.assertLessEqual((base / "run.log").stat().st_size, 512)


class TestImport:
    def test_importing_the_module_runs_nothing_but_definitions(self):
        """There was once a module-level ConversionLogger, so merely importing
        this utility cleared the "conversion_logger" logger's handlers and
        created a logs/ directory with a log file in it. Read from the source
        rather than by running a fresh copy of the module, which is the
        loading of code by path that the code scanners refuse."""
        with open(src.logging_util.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        def is_docstring(node):
            return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)

        for node in tree.body:
            if is_docstring(node):
                continue
            check.assertIsInstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.Try), ast.dump(node)[:80])
            if isinstance(node, ast.Try):  # the import fallback for standalone use
                for inner in node.body + [s for handler in node.handlers for s in handler.body]:
                    check.assertIsInstance(inner, (ast.Import, ast.ImportFrom), ast.dump(inner)[:80])
            if isinstance(node, ast.ClassDef):
                for inner in node.body:
                    check.assertTrue(is_docstring(inner) or isinstance(inner, ast.FunctionDef),
                                     ast.dump(inner)[:80])
