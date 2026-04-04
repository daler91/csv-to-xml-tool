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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..validation_report import ValidationTracker

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
