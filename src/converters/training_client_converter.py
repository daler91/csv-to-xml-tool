"""
Handles the conversion of training client data (Form 641) from CSV to XML.

Training clients fill out a smaller form with different column names than
1-on-1 counseling clients. This converter remaps those columns to the
counseling format and lets the parent CounselingConverter build the same
CounselingInformation XML.
"""

from .counseling_converter import CounselingConverter
from ..config import TrainingClientConfig, ValidationCategory
from .. import data_cleaning
from ..xml_utils import create_element


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
        # The shorter training-client form doesn't collect the fabrication-risk
        # counseling columns; _preprocess_row intentionally injects DEFAULTS for
        # them, so a per-row FABRICATED_DEFAULT warning for every injected value
        # would be a storm about columns the form never had. Only keep warnings
        # for fabrication-risk fields this converter's own input provides.
        self.fabrication_warn_fields -= set(self.training_client_config.DEFAULTS)

    def _preprocess_row(self, row):
        """Remap training client CSV columns to counseling-format columns."""
        # Start with defaults for all absent counseling columns
        remapped = dict(self.training_client_config.DEFAULTS)

        # Map each CSV column to its counseling equivalent (or pass through as-is)
        for csv_col, csv_val in row.items():
            target_col = self.training_client_config.COLUMN_MAPPING.get(csv_col, csv_col)
            remapped[target_col] = csv_val

        # The event's Training Topic is what the attendee sought and received;
        # an explicit counseling-format column in the CSV still wins.
        topic = (row.get('Training Topic') or '').strip()
        if topic:
            if not (row.get('Nature of the Counseling Seeking?') or '').strip():
                remapped['Nature of the Counseling Seeking?'] = topic
            if not (row.get('Services Provided') or '').strip():
                remapped['Services Provided'] = topic

        return remapped

    def _partner_session_number(self, row):
        """Per-attendee campaign-member id; falls back to the event id (the
        remapped Class/Event ID) when the CSV has no Member ID."""
        member_id = (row.get('Member ID') or '').strip()
        return member_id or super()._partner_session_number(row)

    def _build_counselor_record_section(self, parent, row, record_id):
        counselor_record = super()._build_counselor_record_section(parent, row, record_id)
        self._build_training_session(counselor_record, row)
        return counselor_record

    def _build_training_session(self, counselor_record, row):
        """TrainingSession is the last child of CounselorRecord in the XSD
        sequence. Child order: DateTrainingStarted, PartnerTrainingNumber,
        EmployeesTrained, HoursTrained (all optional)."""
        training_session = create_element(counselor_record, 'TrainingSession')
        date_started = data_cleaning.format_date(row.get('Date', ''))  # remapped 'Start Date'
        if date_started:
            create_element(training_session, 'DateTrainingStarted', date_started)
        event_id = (row.get('Activity ID') or '').strip()  # remapped 'Class/Event ID'
        if event_id:
            create_element(training_session, 'PartnerTrainingNumber', event_id)
        create_element(training_session, 'EmployeesTrained', self.training_client_config.EMPLOYEES_TRAINED)
        create_element(training_session, 'HoursTrained', self.training_client_config.HOURS_TRAINED)

    def _resolve_in_business(self, in_business_val, row, record_id):
        """The training-client form asks 'Currently in Business?' but doesn't
        collect the business details (legal entity, counseling sought) that are
        conditionally required for in-business clients. Keep 'Yes' only when the
        CSV actually supplies them; otherwise record the client as not in
        business, with one warning."""
        if in_business_val != 'Yes':
            return in_business_val
        has_legal_entity = bool(
            data_cleaning.split_multi_value(row.get('Legal Entity of Business', ''))
            or (row.get('Other legal entity (specify)') or '').strip())
        has_counseling_seeking = bool(
            data_cleaning.split_multi_value(row.get('Nature of the Counseling Seeking?', '')))
        if has_legal_entity and has_counseling_seeking:
            return in_business_val
        self.validator.add_issue(
            record_id, "warning", ValidationCategory.DOWNGRADED_VALUE, "CurrentlyInBusiness",
            "Client answered 'Yes' to Currently in Business, but the training form doesn't "
            "collect the business details (legal entity, counseling sought) required for "
            "in-business clients, so this client is recorded as not in business in the "
            "federal XML.")
        return 'No'
