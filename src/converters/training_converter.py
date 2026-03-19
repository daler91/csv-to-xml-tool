from .. import data_validation
"""
Handles the conversion of SBA Management Training Reports from CSV to XML.
"""

import pandas as pd
import xml.dom.minidom as md
from xml.etree.ElementTree import Element, tostring
import re

from .base_converter import BaseConverter
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

    def convert(self, input_path: str, output_path: str):
        self.logger.info(f"Starting conversion of training data: {input_path}")

        try:
            df = pd.read_csv(input_path)
            self.logger.info(f"Successfully read CSV with {len(df)} records.")
        except Exception as e:
            self.logger.error(f"Failed to read CSV file: {e}")
            self.validator.add_issue("file", "error", ValidationCategory.FILE_ACCESS, "input_file", f"Failed to read CSV file: {e}")
            raise

        event_id_col = self.config.COLUMN_MAPPING.get("event_id")
        if not event_id_col or event_id_col not in df.columns:
            self.logger.error(f"Required column '{event_id_col}' not found in the CSV.")
            self.validator.add_issue("file", "error", ValidationCategory.MISSING_REQUIRED, event_id_col, "Event ID column is missing.")
            return

        # Pre-validate all rows to ensure they have an event ID
        valid_rows = []
        for index, row in df.iterrows():
            if data_validation.validate_training_record(row, index, self.validator):
                valid_rows.append(row)

        if not valid_rows:
            self.logger.error("No valid rows found in the CSV to process.")
            return

        df_valid = pd.DataFrame(valid_rows)
        event_groups = df_valid.groupby(event_id_col)
        self.logger.info(f"Found {len(event_groups)} unique training events.")

        root = Element('ManagementTrainingReport')
        root.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')

        for event_id, group_df in event_groups:
            if group_df.empty:
                continue

            first_record = group_df.iloc[0]
            self.validator.set_current_record_id(str(event_id))

            try:
                record = create_element(root, 'ManagementTrainingRecord')

                create_element(record, 'PartnerTrainingNumber', str(event_id))

                # FundingSource - optional element based on XSD, but placing it correctly.
                funding_source = self._get_column_value(first_record, 'funding_source')
                if funding_source:
                    create_element(record, 'FundingSource', funding_source)

                location = create_element(record, 'Location')
                create_element(location, 'LocationCode', self.general_config.DEFAULT_LOCATION_CODE)

                date_val = self._get_column_value(first_record, "start_date")
                formatted_date = data_cleaning.format_date(date_val, self.config.DATE_INPUT_FORMATS, self.config.DEFAULT_START_DATE)
                create_element(record, 'DateTrainingStarted', formatted_date)

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
                mapped_topic = data_cleaning.map_value(topic_val, self.config.TRAINING_TOPIC_MAPPINGS, self.config.DEFAULT_TRAINING_TOPIC, False)
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

                self.validator.record_processed(success=True)

            except Exception as e:
                self.logger.error(f"Error processing event {event_id}: {e}", exc_info=True)
                self.validator.add_issue(str(event_id), "error", ValidationCategory.PROCESSING_ERROR, "record", f"Unhandled error: {e}")
                self.validator.record_processed(success=False)

        rough_string = tostring(root, 'utf-8')
        reparsed = md.parseString(rough_string)
        pretty_xml = '\n'.join([line for line in reparsed.toprettyxml(indent="  ").split('\n') if line.strip()])

        with open(output_path, 'w') as f:
            f.write(pretty_xml)
        self.logger.info(f"XML file successfully created at {output_path}")

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

    def _calculate_demographics(self, df):
        demographics = {}
        total = len(df)
        demographics['total'] = max(total, 2) # XSD minimum

        # Helper to resolve a config column key to the actual DataFrame column name
        def resolve_column(column_key):
            possible = self.config.COLUMN_MAPPING.get(column_key, [])
            if isinstance(possible, str):
                possible = [possible]
            return next((c for c in possible if c in df.columns), None)

        # Helper to count matches for a given set of keywords in a specified column
        def count_matches(column_key, keywords_map):
            column_name = resolve_column(column_key)
            if not column_name:
                return 0

            pattern = '|'.join(keywords_map)
            return sum(df[column_name].fillna('').astype(str).str.lower().str.contains(pattern))

        # Business Status
        business_status_col = resolve_column('business_status')
        if business_status_col:
            currently_in_business = sum(df[business_status_col].fillna('').astype(str).str.lower().str.contains('yes|true|1|y'))
            demographics['currently_in_business'] = currently_in_business
            demographics['not_in_business'] = total - currently_in_business

        # Gender, Disability, Military
        demographics['female'] = count_matches('gender', self.config.DEMOGRAPHIC_KEYWORDS['gender']['female'])
        demographics['male'] = count_matches('gender', self.config.DEMOGRAPHIC_KEYWORDS['gender']['male'])
        demographics['disabilities'] = count_matches('disability', ['yes', 'true', '1', 'y'])
        demographics['active_duty'] = count_matches('military_status', self.config.DEMOGRAPHIC_KEYWORDS['military']['active_duty'])
        demographics['veterans'] = count_matches('military_status', self.config.DEMOGRAPHIC_KEYWORDS['military']['veteran'])
        demographics['service_disabled_veterans'] = count_matches('military_status', self.config.DEMOGRAPHIC_KEYWORDS['military']['service_disabled_veteran'])
        demographics['reserve_guard'] = count_matches('military_status', self.config.DEMOGRAPHIC_KEYWORDS['military']['reserve_guard'])
        demographics['military_spouse'] = count_matches('military_status', self.config.DEMOGRAPHIC_KEYWORDS['military']['spouse'])

        # Race
        demographics['race'] = {key: count_matches('race', keywords) for key, keywords in self.config.DEMOGRAPHIC_KEYWORDS['race'].items()}

        # Ethnicity
        hispanic_count = count_matches('ethnicity', self.config.DEMOGRAPHIC_KEYWORDS['ethnicity']['hispanic'])
        ethnicity_col_name = resolve_column('ethnicity')
        non_hispanic_count = 0
        if ethnicity_col_name:
            non_hispanic_mask = (~df[ethnicity_col_name].fillna('').astype(str).str.lower().str.contains('hispanic|latino')) & (df[ethnicity_col_name] != '')
            non_hispanic_count = sum(non_hispanic_mask)
        demographics['ethnicity'] = {'hispanic': hispanic_count, 'non_hispanic': non_hispanic_count}

        # Minorities
        demographics['minorities'] = sum(v for k, v in demographics['race'].items() if k != 'white') + hispanic_count

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