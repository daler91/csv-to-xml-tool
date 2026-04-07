"""
Handles the conversion of training client data (Form 641) from CSV to XML.

Training clients fill out a smaller form with different column names than
1-on-1 counseling clients. This converter remaps those columns to the
counseling format and lets the parent CounselingConverter build the same
CounselingInformation XML.
"""

from .counseling_converter import CounselingConverter
from ..config import TrainingClientConfig


class TrainingClientConverter(CounselingConverter):
    """
    Converter for Training Client 641 data.

    Inherits all XML-building logic from CounselingConverter. Overrides
    _preprocess_row to remap training client CSV columns and inject defaults
    for fields not collected on the shorter training client form.
    """

    def __init__(self, logger, validator):
        super().__init__(logger, validator)
        self.training_client_config = TrainingClientConfig()

    def _preprocess_row(self, row):
        """Remap training client CSV columns to counseling-format columns."""
        # Start with defaults for all absent counseling columns
        remapped = dict(self.training_client_config.DEFAULTS)

        # Map each CSV column to its counseling equivalent (or pass through as-is)
        for csv_col, csv_val in row.items():
            target_col = self.training_client_config.COLUMN_MAPPING.get(csv_col, csv_col)
            remapped[target_col] = csv_val

        return remapped
