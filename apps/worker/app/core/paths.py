"""Locating the bundled XSD schemas.

The worker validates every conversion against the SBA schemas in ``schemas/``,
so it has to find that directory in two different layouts:

===========  ==========================  =====================================
Layout       ``__file__`` lives at       ``schemas/`` lives at
===========  ==========================  =====================================
repo         ``apps/worker/app/…``       ``<root>/schemas``, reached via the
                                         tracked ``apps/worker/schemas``
                                         symlink -> ``../../schemas``
Docker       ``/app/app/…``              ``/app/schemas`` (``COPY schemas/``)
===========  ==========================  =====================================

Both resolve as "two directories up from the ``app`` package, then
``schemas``" -- the symlink exists precisely so the same relative path works in
a checkout. A previous version of this default walked up *three* directories,
which resolved to ``apps/schemas`` in the repo and ``/schemas`` in Docker.
Neither exists, and nothing failed loudly: ``run_conversion`` skipped
validation and reported ``xsd_valid=false`` with an empty error list, while
``/validate-xsd`` and ``/fix-xml`` returned the opaque string
``"Validation error"`` for every document. Hence ``verify_schemas_dir()``,
which the app calls at startup so a bad path stops the worker instead of
silently degrading every filing it processes.

Fail-closed, matching the convention in ``core/auth.py``.
"""

import os

# Which XSD each schema/converter type validates against. training-client
# output is Form 641 counseling-format XML, so it uses the counseling XSD.
XSD_MAP = {
    "counseling": "SBA_NEXUS_Counseling-2-14.xsd",
    "training": "SBA_NEXUS_Training-2-25-2025.xsd",
    "training-client": "SBA_NEXUS_Counseling-2-14.xsd",
}

# A directory is only the schemas directory if it actually holds the XSDs --
# checking for the directory alone would accept an empty leftover.
REQUIRED_SCHEMA_FILES = ("SBA_NEXUS_Counseling-2-14.xsd", "SBA_NEXUS_Training-2-25-2025.xsd")

# app/core/paths.py -> app/core -> app -> the directory holding `schemas`.
_APP_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _holds_schemas(candidate: str) -> bool:
    return os.path.isdir(candidate) and all(
        os.path.exists(os.path.join(candidate, name)) for name in REQUIRED_SCHEMA_FILES
    )


def default_schemas_dir() -> str:
    """Best-effort location of the bundled schemas, used when SCHEMAS_DIR is unset.

    Tries the expected relative path first, then walks up looking for a
    ``schemas/`` directory that holds the XSDs. The walk-up is a fallback for
    checkouts where ``apps/worker/schemas`` is not a working symlink -- Git on
    Windows writes a plain text file containing the link target unless symlink
    support is enabled.

    Always returns a path, never raises: an unresolvable location is reported
    by verify_schemas_dir() at startup, so the failure surfaces in one place
    with one message rather than at import time in three modules.
    """
    expected = os.path.normpath(os.path.join(_APP_PACKAGE_DIR, "..", "schemas"))
    if _holds_schemas(expected):
        return expected

    directory = _APP_PACKAGE_DIR
    while True:
        candidate = os.path.join(directory, "schemas")
        if _holds_schemas(candidate):
            return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            return expected  # report the path we expected, not the filesystem root
        directory = parent


def verify_schemas_dir(schemas_dir: str) -> None:
    """Raise RuntimeError unless `schemas_dir` holds every required XSD.

    Called from the app's lifespan so a misconfigured deployment fails to start
    rather than silently returning "invalid, no reasons given" for every
    document it is asked to validate.
    """
    if not os.path.isdir(schemas_dir):
        raise RuntimeError(
            f"Schemas directory not found: {schemas_dir!r}. "
            f"Set SCHEMAS_DIR to the directory containing {', '.join(REQUIRED_SCHEMA_FILES)}."
        )
    missing = [
        name for name in REQUIRED_SCHEMA_FILES
        if not os.path.exists(os.path.join(schemas_dir, name))
    ]
    if missing:
        raise RuntimeError(
            f"Schemas directory {schemas_dir!r} is missing: {', '.join(missing)}. "
            "XSD validation cannot run without these files."
        )
