"""
Handles the conversion of SBA Management Training Reports from CSV to XML.
"""

from .. import data_validation
import pandas as pd
import xml.etree.ElementTree as ET
import re

from .base_converter import BaseConverter, EmptyCSVError
from ..config import TrainingConfig, GeneralConfig, ValidationCategory
from .. import data_cleaning
from ..xml_utils import create_element

class TrainingConverter(BaseConverter):
    """
    Converter for Management Training Report data.
    """
    def __init__(self, logger, validator):
        super().__init__(logger, validator)
        self.config = TrainingConfig()
        self.general_config = GeneralConfig()

    def _get_column_value(self, record, key, default=''):
        """
        Gets a value from a record (pandas Series) using a list of possible column names from config.
        """
        possible_columns = self.config.COLUMN_MAPPING.get(key, [])
        if isinstance(possible_columns, str):
            possible_columns = [possible_columns]

        for col in possible_columns:
            if col in record and not pd.isna(record[col]):
                return str(record[col])
        return default

    def _read_and_validate_csv(self, input_path):
        """Read CSV, validate columns and rows. Returns (event_groups, event_id_col) or (None, None)."""
        try:
            # CONV-2: explicit utf-8-sig + string dtype (both were missing) and
            # normalize header whitespace so lookups match the other read paths.
            df = pd.read_csv(input_path, encoding='utf-8-sig', dtype=str)
            df.columns = [data_cleaning.normalize_header(c) for c in df.columns]
            self.logger.info(f"Successfully read CSV with {len(df)} records.")
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as e:
            self.logger.error(f"Failed to read CSV file: {e}")
            self.validator.add_issue("file", "error", ValidationCategory.FILE_ACCESS, "input_file", f"Failed to read CSV file: {e}")
            raise

        if df.empty:
            # CONV-6: a headers-only / empty CSV must fail, not return silently.
            self.validator.add_issue("file", "error", ValidationCategory.MISSING_REQUIRED, "input_file", "CSV has headers but no data rows to convert.")
            raise EmptyCSVError("CSV has no data rows to convert.")

        event_id_col = self.config.COLUMN_MAPPING.get("event_id")
        if not event_id_col or event_id_col not in df.columns:
            self.logger.error(f"Required column '{event_id_col}' not found in the CSV.")
            self.validator.add_issue("file", "error", ValidationCategory.MISSING_REQUIRED, event_id_col, "Event ID column is missing.")
            return None, None

        valid_rows = [row for index, row in df.iterrows() if data_validation.validate_training_record(row, index, self.validator)]
        if not valid_rows:
            self.logger.error("No valid rows found in the CSV to process.")
            return None, None

        df_valid = pd.DataFrame(valid_rows)
        event_groups = df_valid.groupby(event_id_col)
        self.logger.info(f"Found {len(event_groups)} unique training events.")
        return event_groups, event_id_col

    def _write_xml_output(self, root, output_path):
        """Format and write XML tree to output file."""
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(output_path, encoding='utf-8', xml_declaration=True)
        self.logger.info(f"XML file successfully created at {output_path}")

    def _build_training_record(self, root, event_id, group_df):
        """Build a single ManagementTrainingRecord element."""
        first_record = group_df.iloc[0]
        self.validator.set_current_record_id(str(event_id))

        record = create_element(root, 'ManagementTrainingRecord')
        create_element(record, 'PartnerTrainingNumber', str(event_id))

        funding_source = self._get_column_value(first_record, 'funding_source')
        if funding_source:
            valid_funding = self._resolve_funding_source(funding_source, event_id)
            if valid_funding:
                create_element(record, 'FundingSource', valid_funding)

        location = create_element(record, 'Location')
        create_element(location, 'LocationCode', self.general_config.DEFAULT_LOCATION_CODE)

        date_val = self._get_column_value(first_record, "start_date")
        formatted_date = data_cleaning.format_date(date_val, self.config.DATE_INPUT_FORMATS, self.config.DEFAULT_START_DATE)
        create_element(record, 'DateTrainingStarted', formatted_date)
        if data_cleaning.is_ambiguous_date(date_val):
            # CONV-3: emitted month-first, but flag the ambiguity for human review.
            self.validator.add_issue(
                str(event_id), "warning", ValidationCategory.AMBIGUOUS_DATE,
                "DateTrainingStarted",
                f"Start date '{str(date_val).strip()}' is ambiguous between MM/DD "
                f"and DD/MM; interpreted month-first as {formatted_date}.",
            )

        create_element(record, 'NumberOfSessions', self.config.DEFAULT_TRAINING_SESSIONS)
        create_element(record, 'TotalTrainingHours', self.config.DEFAULT_TRAINING_HOURS)

        title_val = self._get_column_value(first_record, "event_name")
        if not title_val:
            title_val = f"{self.config.DEFAULT_TRAINING_EVENT_TITLE_PREFIX}{event_id}"
        create_element(record, 'TrainingTitle', title_val)

        self._build_location_section(record, first_record)
        demographics = self._calculate_demographics(group_df)
        self._build_demographics_section(record, demographics)

        topic_val = self._get_column_value(first_record, "training_topic")
        mapped_topic = self._resolve_training_topic(topic_val, event_id)
        training_topic_element = create_element(record, 'TrainingTopic')
        create_element(training_topic_element, 'Code', mapped_topic)

        partners_element = create_element(record, 'TrainingPartners')
        create_element(partners_element, 'Code', self.config.DEFAULT_TRAINING_PARTNER_CODE)

        format_val = self._get_column_value(first_record, "event_type")
        program_format_text = data_cleaning.map_value(format_val, self.config.PROGRAM_FORMAT_MAPPINGS, self.config.DEFAULT_PROGRAM_FORMAT, False)
        create_element(record, 'ProgramFormatType', program_format_text)

        create_element(record, 'DollarAmountOfFees', self.config.DEFAULT_TRAINING_FEES)
        language_element = create_element(record, 'Language')
        create_element(language_element, 'Code', self.general_config.DEFAULT_LANGUAGE)

        cosponsor_name = self._get_column_value(first_record, "cosponsor")
        if cosponsor_name and cosponsor_name.lower() != 'n/a':
            create_element(record, 'CosponsorsName', cosponsor_name)

    def convert(self, input_path: str, output_path: str):
        self.logger.info(f"Starting conversion of training data: {input_path}")

        event_groups, event_id_col = self._read_and_validate_csv(input_path)
        if event_groups is None:
            return

        root = ET.Element('ManagementTrainingReport')
        root.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')

        # Training converter aggregates per event, so "progress" is
        # measured in event groups rather than CSV rows. Call the
        # callback every N groups so the web progress bar advances.
        total_events = len(event_groups)
        self._report_progress(0, total_events)

        for i, (event_id, group_df) in enumerate(event_groups, 1):
            if group_df.empty:
                self._maybe_report_progress(i, total_events, every=5)
                continue
            try:
                self._build_training_record(root, event_id, group_df)
                self.validator.record_processed(success=True)
            except (ValueError, KeyError, AttributeError) as e:
                self.logger.error(f"Error processing event {event_id}: {e}", exc_info=True)
                self.validator.add_issue(str(event_id), "error", ValidationCategory.PROCESSING_ERROR, "record", f"Error processing event: {e}")
                self.validator.record_processed(success=False)

            self._maybe_report_progress(i, total_events, every=5)

        self._report_progress(total_events, total_events)

        self._write_xml_output(root, output_path)

    def _build_location_section(self, parent, record):
        training_location = create_element(parent, 'TrainingLocation')

        city = self._get_column_value(record, 'city')
        state = self._get_column_value(record, 'state')
        zip_code_raw = self._get_column_value(record, 'zip')

        zip_match = re.search(r'\d{5}', zip_code_raw)
        zip_code = zip_match.group(0) if zip_match else ''

        if not (city and state and zip_code):
            self.logger.info(f"Using default location for event {self.validator.current_record_id}")
            city = self.config.DEFAULT_LOCATION['city']
            state = self.config.DEFAULT_LOCATION['state']
            zip_code = self.config.DEFAULT_LOCATION['zip']

        create_element(training_location, 'City', city)
        create_element(training_location, 'State', data_cleaning.standardize_state_name(state))
        create_element(training_location, 'ZipCode', zip_code)
        country_element = create_element(training_location, 'Country')
        create_element(country_element, 'Code', self.config.DEFAULT_LOCATION['country'])

    def _resolve_column(self, df, column_key):
        """Resolve a config column key to the actual DataFrame column name."""
        possible = self.config.COLUMN_MAPPING.get(column_key, [])
        if isinstance(possible, str):
            possible = [possible]
        return next((c for c in possible if c in df.columns), None)

    def _resolve_funding_source(self, funding_source, event_id):
        """Return the funding source iff it is a valid XSD enumeration value, else None.

        FundingSource is optional; a non-enumerated label (e.g. a WBC "CORE"/"Federal"
        funding string) must be omitted rather than emitted, or the XML fails schema
        validation. Unrecognized values are flagged for review.
        """
        cleaned = str(funding_source).strip()
        for valid_source in self.config.VALID_FUNDING_SOURCES:
            if valid_source.lower() == cleaned.lower():
                return valid_source
        self.validator.add_issue(
            str(event_id), "warning", ValidationCategory.INVALID_VALUE, "FundingSource",
            f"Funding Source '{cleaned}' is not a recognized SBA funding code; omitted from the XML.",
        )
        return None

    def _resolve_training_topic(self, topic_val, event_id):
        """Resolve a CSV Training Topic to a valid XSD TrainingTopic/Code.

        A value already in the SBA controlled vocabulary is returned verbatim (so a
        populated "Training Topic" column is authoritative); otherwise a known synonym
        is translated; an empty value falls back to the default silently; an
        unrecognized value falls back to the default and is flagged for review.
        """
        cleaned = str(topic_val).strip() if topic_val else ''
        if not cleaned:
            return self.config.DEFAULT_TRAINING_TOPIC
        for valid_topic in self.config.VALID_TRAINING_TOPICS:
            if valid_topic.lower() == cleaned.lower():
                return valid_topic
        mapped = data_cleaning.map_value(cleaned, self.config.TRAINING_TOPIC_MAPPINGS, None, False)
        if mapped:
            return mapped
        self.validator.add_issue(
            str(event_id), "warning", ValidationCategory.INVALID_VALUE, "TrainingTopic",
            f"Unrecognized Training Topic '{cleaned}'; defaulted to '{self.config.DEFAULT_TRAINING_TOPIC}'.",
        )
        return self.config.DEFAULT_TRAINING_TOPIC

    def _calculate_demographics(self, df):
        """Aggregate per-attendee rows for one event into demographic counts.

        Each attendee row is classified by its controlled-vocabulary value (reusing
        data_cleaning helpers) instead of loose substring matching, so "Prefer not to
        say"/blank fall into no bucket, "Female" is never miscounted as Male, and "Non
        Hispanic or Latino" is never miscounted as Hispanic.
        """
        demographics = {}
        total = len(df)
        demographics['total'] = max(total, 1)  # XSD requires Total >= 1

        gender_col = self._resolve_column(df, 'gender')
        ethnicity_col = self._resolve_column(df, 'ethnicity')
        race_col = self._resolve_column(df, 'race')
        military_col = self._resolve_column(df, 'military_status')
        disability_col = self._resolve_column(df, 'disability')
        business_col = self._resolve_column(df, 'business_status')

        race_keywords = self.config.DEMOGRAPHIC_KEYWORDS['race']
        military_keywords = self.config.DEMOGRAPHIC_KEYWORDS['military']

        female = male = 0
        currently_in_business = not_in_business = 0
        disabilities = 0
        military_counts = {key: 0 for key in military_keywords}
        race_counts = {key: 0 for key in race_keywords}
        hispanic = non_hispanic = 0
        minorities = 0

        for _, row in df.iterrows():
            if gender_col:
                sex = data_cleaning.map_gender_to_sex(row.get(gender_col))
                if sex == 'Female':
                    female += 1
                elif sex == 'Male':
                    male += 1

            if business_col:
                business_val = row.get(business_col)
                if data_cleaning.is_affirmative(business_val):
                    currently_in_business += 1
                elif data_cleaning.is_negative(business_val):
                    not_in_business += 1

            if disability_col and data_cleaning.is_affirmative(row.get(disability_col)):
                disabilities += 1

            if military_col:
                for category in data_cleaning.classify_military(row.get(military_col), military_keywords):
                    military_counts[category] += 1

            person_races = data_cleaning.classify_races(row.get(race_col), race_keywords) if race_col else set()
            for category in person_races:
                race_counts[category] += 1

            person_ethnicity = data_cleaning.classify_ethnicity(row.get(ethnicity_col)) if ethnicity_col else None
            if person_ethnicity == 'hispanic':
                hispanic += 1
            elif person_ethnicity == 'non_hispanic':
                non_hispanic += 1

            # Underserved/minority = distinct attendees who are Hispanic OR any non-white
            # race, counted per person (not a sum of category counts) so a multi-race
            # attendee is never double-counted.
            if person_ethnicity == 'hispanic' or any(c != 'white' for c in person_races):
                minorities += 1

        demographics['female'] = female
        demographics['male'] = male
        if business_col:
            demographics['currently_in_business'] = currently_in_business
            demographics['not_in_business'] = not_in_business
        demographics['disabilities'] = disabilities
        demographics['active_duty'] = military_counts.get('active_duty', 0)
        demographics['veterans'] = military_counts.get('veteran', 0)
        demographics['service_disabled_veterans'] = military_counts.get('service_disabled_veteran', 0)
        demographics['reserve_guard'] = military_counts.get('reserve_guard', 0)
        demographics['military_spouse'] = military_counts.get('spouse', 0)
        demographics['race'] = race_counts
        demographics['ethnicity'] = {'hispanic': hispanic, 'non_hispanic': non_hispanic}
        demographics['minorities'] = minorities

        return demographics

    def _build_demographics_section(self, parent, demographics):
        number_trained = create_element(parent, 'NumberTrained')
        create_element(number_trained, 'Total', str(demographics.get('total', 0)))

        # Simple demographics
        key_to_xml_map = {
            'currently_in_business': 'CurrentlyInBusiness',
            'not_in_business': 'NotYetInBusiness',
            'disabilities': 'PersonWithDisabilities',
            'female': 'Female',
            'male': 'Male',
            'active_duty': 'ActiveDuty',
            'veterans': 'Veterans',
            'service_disabled_veterans': 'ServiceDisabledVeterans',
            'reserve_guard': 'MemberOfReserveOrNationalGuard',
            'military_spouse': 'SpouseOfMilitaryMember'
        }
        for key, xml_tag in key_to_xml_map.items():
            if demographics.get(key, 0) > 0:
                create_element(number_trained, xml_tag, str(demographics[key]))

        # Race
        if any(v > 0 for v in demographics.get('race', {}).values()):
            race_element = create_element(number_trained, 'Race')
            race_map = {'black': 'BlackOrAfricanAmerican', 'native_american': 'NativeAmericanOrAlaskaNative', 'pacific_islander': 'NativeHawaiianOrPacificIslander'}
            for key, count in demographics['race'].items():
                if count > 0:
                    xml_key = race_map.get(key, key.replace('_', ' ').title().replace(' ', ''))
                    create_element(race_element, xml_key, str(count))

        # Ethnicity
        if any(v > 0 for v in demographics.get('ethnicity', {}).values()):
            ethnicity_element = create_element(number_trained, 'Ethnicity')
            if demographics['ethnicity'].get('hispanic', 0) > 0:
                create_element(ethnicity_element, 'HispanicOrLatinoOrigin', str(demographics['ethnicity']['hispanic']))
            if demographics['ethnicity'].get('non_hispanic', 0) > 0:
                create_element(ethnicity_element, 'NonHispanicOrLatinoOrigin', str(demographics['ethnicity']['non_hispanic']))

        # Minorities
        if demographics.get('minorities', 0) > 0:
            minorities_element = create_element(parent, 'NumberUnderservedTrained')
            create_element(minorities_element, 'Total', str(demographics['minorities']))