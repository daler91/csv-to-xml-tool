"""Shared pytest path setup for the repo-root test suite.

The existing tests import the shared Python library as ``src.*`` (each test
inserts the repo root on ``sys.path`` itself). The worker registry tests
additionally import the FastAPI worker package as ``app.*`` — the same import
root the container uses (``uvicorn app.main:app``). Putting both roots on
``sys.path`` here, at collection time, lets either import style resolve without
each test having to repeat the boilerplate.
"""

import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_WORKER_ROOT = os.path.join(_REPO_ROOT, "apps", "worker")

for _path in (_REPO_ROOT, _WORKER_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)
