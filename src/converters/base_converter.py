from __future__ import annotations

"""
Defines the base class for all data converters.

This module provides an abstract base class (ABC) that sets the common interface
for all converter implementations. Each converter must handle its own specific
logic for reading, processing, and writing data, but must conform to the
`convert` method signature defined here.
"""

import abc
import logging
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from ..validation_report import ValidationTracker

# Type alias for the progress callback signature.
# First int is rows processed so far, second is total rows.
ProgressCallback = Callable[[int, int], None]

class BaseConverter(abc.ABC):
    """
    Abstract Base Class for all data converters.

    This class defines the standard interface for converters. It ensures that
    each converter is initialized with essential services like a logger and a
    validation tracker.
    """

    def __init__(self, logger: logging.Logger, validator: ValidationTracker) -> None:
        """
        Initializes the converter with a logger and a validator.

        Args:
            logger: An instance of a logger for logging messages.
            validator: An instance of ValidationTracker to track validation issues.
        """
        self.logger = logger
        self.validator = validator
        # Optional progress callback set by callers that want row-level
        # progress updates (e.g. the FastAPI worker, which polls this
        # back into an in-memory registry the web app reads to draw
        # the progress bar). None by default so the CLI path is
        # unchanged. See UX_REVIEW.md §3.6.
        self.progress_callback: Optional[ProgressCallback] = None

    def _report_progress(self, processed: int, total: int) -> None:
        """Report progress to the callback if one is set. No-op otherwise."""
        if self.progress_callback is not None:
            try:
                self.progress_callback(processed, total)
            except Exception:  # noqa: BLE001 - never let progress errors break conversion
                # Progress reporting is best-effort. If the callback
                # raises (e.g. the registry was cleared while the
                # conversion was still running), swallow the error so
                # the conversion itself is unaffected.
                pass

    def _maybe_report_progress(
        self, processed: int, total: int, every: int = 25
    ) -> None:
        """Debounced progress report.

        Calls the callback roughly once every ``every`` rows so we
        don't hammer the registry on tiny files. Always reports the
        last row so the bar lands cleanly at the terminal count.
        """
        if processed == total or processed % every == 0:
            self._report_progress(processed, total)

    @abc.abstractmethod
    def convert(self, input_path: str, output_path: str) -> None:
        """
        Performs the data conversion.

        This method must be implemented by all subclasses. It should contain the
        core logic for reading the input file, processing the data, and writing
        the output file.

        Args:
            input_path: The full path to the input data file.
            output_path: The full path where the output file should be saved.

        Raises:
            NotImplementedError: If the subclass does not implement this method.
        """
        raise NotImplementedError("Each converter must implement the 'convert' method.")
