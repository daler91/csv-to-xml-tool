"""Filesystem path confinement for the command-line tools (CWE-22 hardening).

Mirrors the worker's ``apps/worker/app/core/security.py``: resolve a
user-influenced path to its canonical form and require it to stay within an
allowed base directory, raising on escape. Unlike the worker -- which confines
everything to a fixed ``DATA_DIR`` -- the CLI legitimately writes wherever the
operator points it, so the base **defaults to the current working directory**
and can be widened with the ``SBA_OUTPUT_BASE`` environment variable.

Each CLI entry point seeds ``SBA_OUTPUT_BASE`` with its natural root via
``os.environ.setdefault`` (``run.py`` uses its own script directory, ``main.py``
uses the cwd) so the existing relative-path defaults (``logs/``, ``reports/``,
``output/``) keep resolving the same way regardless of where the process was
started, while an absolute path that points outside the base is refused.
"""

import os


def output_base() -> str:
    """Return the directory that CLI writes are confined to.

    ``SBA_OUTPUT_BASE`` wins when set; otherwise the current working directory.
    Canonicalised (``realpath``) so containment checks compare like with like.
    """
    return os.path.realpath(os.environ.get("SBA_OUTPUT_BASE") or os.getcwd())


def resolve_within(base: str, path: str) -> str:
    """Resolve ``path`` and confine it within ``base``.

    A relative ``path`` is resolved against ``base``; an absolute ``path`` is
    kept as given. Returns the canonical (``realpath``) location.

    Raises ``ValueError`` if the resolved path escapes ``base`` -- via ``..`` or
    an absolute path pointing outside it -- naming ``SBA_OUTPUT_BASE`` as the way
    to permit a different location. ``commonpath`` is used (rather than a string
    prefix) so a sibling like ``/data-evil`` is not treated as inside ``/data``.
    """
    base_real = os.path.realpath(base)
    resolved = os.path.realpath(os.path.join(base_real, path))
    if os.path.commonpath([base_real, resolved]) != base_real:
        raise ValueError(
            f"Refusing to write outside {base_real!r}: {path!r}. "
            "Set SBA_OUTPUT_BASE to allow a different location."
        )
    return resolved
