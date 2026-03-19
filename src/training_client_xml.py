"""
Training Client XML Generator for SBA NEXUS Counseling.
This module handles converting class/event CSV data to valid XML for training clients,
with comprehensive defaults for required fields.
"""

import csv
import xml.etree.ElementTree as ET
import os
from datetime import datetime
import argparse
import logging # Keep standard logging import for levels like logging.INFO

# Import data cleaning functions from existing module
from .data_cleaning import (
    clean_phone_number, format_date, clean_whitespace, 
    map_gender_to_sex, split_multi_value, clean_numeric, clean_percentage,
    standardize_country_code, standardize_state_name
)

# Import constants from .config (if needed)
from .config import (
    DEFAULT_LOCATION_CODE, DEFAULT_LANGUAGE
)

# ================ DEFAULT VALUES ================
# Iowa-specific defaults
DEFAULT_STATE = "Iowa"
DEFAULT_CITY = "Des Moines"
DEFAULT_ZIP_CODE = "50312"
DEFAULT_COUNTRY = "United States"

# Client information defaults
DEFAULT_LAST_NAME = "Attendee"  # Fallback when last name is missing
DEFAULT_FIRST_NAME = "Training"  # Fallback when first name is missing
DEFAULT_RACE = "Prefer not to say"
DEFAULT_ETHNICITY = "Prefer not to say"
DEFAULT_DISABILITY = "Prefer not to say"
DEFAULT_MILITARY_STATUS = "Prefer not to say"
DEFAULT_BUSINESS_STATUS = "No"
DEFAULT_SURVEY_AGREEMENT = "No"
DEFAULT_SIGNATURE_ON_FILE = "No"

# Session defaults
DEFAULT_SESSION_TYPE = "Training"
DEFAULT_LANGUAGE = "English"
DEFAULT_COUNSELING_TYPE = "Business Start-up/Preplanning"
DEFAULT_COUNSELOR_NAME = "Class Instructor"
DEFAULT_TRAINING_HOURS = 2.0
DEFAULT_EMPLOYEES_TRAINED = 1

# ================ HELPER FUNCTIONS ================

def get_value_with_default(row, field_name, default_value):
    """
    Gets a value from the row dictionary with a default if missing or empty.
    
    Args:
        row: Dictionary of field values
        field_name: Name of the field
        default_value: Default value to use if missing or empty
        
    Returns:
        The field value or default if missing/empty
    """
    value = row.get(field_name, '')
    if not value or str(value).strip() == "" or str(value).lower() == "nan":
        return default_value
    return value

# ================ XML GENERATION FUNCTIONS ================
from .xml_utils import create_element

def build_client_request_section(counseling_record, row, record_id, logger):
    """
    Builds the ClientRequest section of the XML with comprehensive defaults.
    """
    client_request = create_element(counseling_record, 'ClientRequest')
    
    # Name information - applying defaults if missing or empty
    client_name = create_element(client_request, 'ClientNamePart1')
    create_element(client_name, 'Last', get_value_with_default(row, 'Last Name', DEFAULT_LAST_NAME))
    create_element(client_name, 'First', get_value_with_default(row, 'First Name', DEFAULT_FIRST_NAME))
    create_element(client_name, 'Middle', row.get('Middle Name', ''))
    
    # Contact information
    create_element(client_request, 'Email', row.get('Email', ''))
    phone = create_element(client_request, 'PhonePart1')
    create_element(phone, 'Primary', clean_phone_number(row.get('Phone', '')))
    create_element(phone, 'Secondary', '')
    
    # Address information - using Iowa defaults
    address = create_element(client_request, 'AddressPart1')
    create_element(address, 'Street1', row.get('Mailing Street', ''))
    create_element(address, 'Street2', '')
    
    # Always use defaults for these required fields if missing or empty
    city_value = get_value_with_default(row, 'Mailing City', DEFAULT_CITY)
    create_element(address, 'City', city_value)
    
    state_value = get_value_with_default(row, 'Mailing State/Province', DEFAULT_STATE)
    standardized_state = standardize_state_name(state_value)
    create_element(address, 'State', standardized_state)
    
    zip_code = get_value_with_default(row, 'Mailing Zip/Postal Code', DEFAULT_ZIP_CODE)
    create_element(address, 'ZipCode', zip_code)
    create_element(address, 'Zip4Code', '')
    
    # Country section with standardization
    country = create_element(address, 'Country')
    country_value = get_value_with_default(row, 'Mailing Country', DEFAULT_COUNTRY)
    standardized_country = standardize_country_code(country_value)
    create_element(country, 'Code', standardized_country)
    
    # Survey agreement and signature
    survey_agreement = get_value_with_default(row, 'Agree to Impact Survey', DEFAULT_SURVEY_AGREEMENT)
    create_element(client_request, 'SurveyAgreement', survey_agreement)
    
    signature = create_element(client_request, 'ClientSignature')
    signature_date = format_date(row.get('Client Signature - Date', ''))
    create_element(signature, 'Date', signature_date)
    
    signature_onfile = get_value_with_default(row, 'Client Signature(On File)', DEFAULT_SIGNATURE_ON_FILE)
    if signature_onfile == '1' or signature_onfile == 1:
        signature_onfile = 'Yes'
    else:
        signature_onfile = 'No'
    create_element(signature, 'OnFile', signature_onfile)

def build_client_intake_section(counseling_record, row, record_id, logger):
    """
    Builds the ClientIntake section of the XML with comprehensive defaults.
    """
    client_intake = create_element(counseling_record, 'ClientIntake')
    
    # Race information (multi-value field)
    race = create_element(client_intake, 'Race')
    race_codes = split_multi_value(row.get('Race', ''))
    # If no race codes specified, use a default to satisfy the XSD
    if not race_codes:
        create_element(race, 'Code', DEFAULT_RACE)
    else:
        for code in race_codes:
            create_element(race, 'Code', code)
    create_element(race, 'SelfDescribedRace', '')
    
    # Demographics - required fields with defaults
    ethnicity = get_value_with_default(row, 'Ethnicity', DEFAULT_ETHNICITY)
    create_element(client_intake, 'Ethnicity', ethnicity)
    
    # Convert Gender to Sex (XSD requirement)
    sex_value = map_gender_to_sex(row.get('Gender', ''))
    if sex_value:
        create_element(client_intake, 'Sex', sex_value)
    
    disability = get_value_with_default(row, 'Disability', DEFAULT_DISABILITY)
    create_element(client_intake, 'Disability', disability)
    
    # Military information - required with default
    military_status = get_value_with_default(row, 'Veteran Status', DEFAULT_MILITARY_STATUS)
    create_element(client_intake, 'MilitaryStatus', military_status)
    
    # Add Branch of Service only for military personnel
    if military_status not in ['Prefer not to say', 'No military service']:
        branch = get_value_with_default(row, 'Branch Of Service', 'Prefer not to say')
        create_element(client_intake, 'BranchOfService', branch)
    
    # Referral information (Media)
    media_codes = split_multi_value(row.get('What Prompted you to contact us?', ''))
    if media_codes or row.get('Internet (specify)'):
        media = create_element(client_intake, 'Media')
        for code in media_codes:
            create_element(media, 'Code', code)
        media_other = row.get('Internet (specify)', '')
        if media_other:
            create_element(media, 'Other', media_other)
    
    # Business information - required fields with defaults
    currently_in_business = get_value_with_default(row, 'Currently in Business?', DEFAULT_BUSINESS_STATUS)
    create_element(client_intake, 'CurrentlyInBusiness', currently_in_business)
    
    currently_exporting = get_value_with_default(row, 'Are you currently exporting?', DEFAULT_BUSINESS_STATUS)
    create_element(client_intake, 'CurrentlyExporting', currently_exporting)
    
    company_name = row.get('Account Name', '')
    create_element(client_intake, 'CompanyName', company_name)
    
    business_type = row.get('Type of Business', '')
    if business_type:
        create_element(client_intake, 'BusinessType', business_type)
    
    # Business ownership
    business_ownership = create_element(client_intake, 'BusinessOwnership')
    female_ownership = clean_numeric(row.get('Business Ownership - % Female', '0'))
    create_element(business_ownership, 'Female', female_ownership)
    
    # Business operations
    conducting_online = get_value_with_default(row, 'Conduct Business Online?', DEFAULT_BUSINESS_STATUS)
    create_element(client_intake, 'ConductingBusinessOnline', conducting_online)
    
    certified_8a = get_value_with_default(row, '8(a) Certified?', DEFAULT_BUSINESS_STATUS)
    create_element(client_intake, 'ClientIntake_Certified8a', certified_8a)
    
    # Employee and financial information
    employees = row.get('Total Number of Employees', '0')
    create_element(client_intake, 'TotalNumberOfEmployees', clean_numeric(employees))
    
    # Financial information
    client_annual_income = create_element(client_intake, 'ClientAnnualIncomePart2')
    gross_revenue = row.get('Gross Revenues/Sales', '0')
    create_element(client_annual_income, 'GrossRevenues', clean_numeric(gross_revenue))
    
    profit_loss = row.get('Profits/Losses', '0')
    create_element(client_annual_income, 'ProfitLoss', clean_numeric(profit_loss))
    
    create_element(client_annual_income, 'ExportGrossRevenuesOrSales', '0')
    
    # Legal entity information
    legal_entity_codes = split_multi_value(row.get('Legal Entity of Business', ''))
    if legal_entity_codes or row.get('Other legal entity (specify)'):
        legal_entity = create_element(client_intake, 'LegalEntity')
        for code in legal_entity_codes:
            create_element(legal_entity, 'Code', code)
        legal_entity_other = row.get('Other legal entity (specify)', '')
        if legal_entity_other:
            create_element(legal_entity, 'Other', legal_entity_other)
    
    # Rural/Urban status - required with default
    create_element(client_intake, 'Rural_vs_Urban', 'Undetermined')
    
    # Counseling seeking information
    counseling_seeking_codes = split_multi_value(row.get('Nature of the Counseling Seeking?', ''))
    if counseling_seeking_codes:
        counseling_seeking = create_element(client_intake, 'CounselingSeeking')
        for code in counseling_seeking_codes:
            create_element(counseling_seeking, 'Code', code)
        create_element(counseling_seeking, 'Other', '')

def build_training_counselor_record_section(counseling_record, row, record_id, logger, training_hours=DEFAULT_TRAINING_HOURS):
    """
    Builds the CounselorRecord section with training-specific elements and defaults.
    
    Args:
        counseling_record: The parent XML element
        row: Dictionary of field values
        record_id: ID of the record
        logger: Logger instance
        training_hours: Default training hours to use if not specified in CSV
    """
    counselor_record = create_element(counseling_record, 'CounselorRecord')
    
    # CHANGE 3: Use Class Member ID as the PartnerSessionNumber, generate if missing
    session_number = get_value_with_default(row, 'Class Member ID', f"TRN{record_id}")
    create_element(counselor_record, 'PartnerSessionNumber', session_number)
    
    # Still need Class/Event ID for the training section
    class_id = get_value_with_default(row, 'Class/Event ID', f"CLS{record_id}")
    
    # Contact information - repeat from ClientRequest with defaults
    counselor_name = create_element(counselor_record, 'ClientNamePart3')
    create_element(counselor_name, 'Last', get_value_with_default(row, 'Last Name', DEFAULT_LAST_NAME))
    create_element(counselor_name, 'First', get_value_with_default(row, 'First Name', DEFAULT_FIRST_NAME))
    create_element(counselor_name, 'Middle', row.get('Middle Name', ''))
    
    # Email and phone (optional)
    create_element(counselor_record, 'Email', row.get('Email', ''))
    
    phone = create_element(counselor_record, 'PhonePart3')
    create_element(phone, 'Primary', clean_phone_number(row.get('Phone', '')))
    create_element(phone, 'Secondary', '')
    
    # Address information (optional but adding for completeness)
    address = create_element(counselor_record, 'AddressPart3')
    create_element(address, 'Street1', row.get('Mailing Street', ''))
    create_element(address, 'Street2', '')
    
    # Always use defaults for these fields if missing or empty
    city_value = get_value_with_default(row, 'Mailing City', DEFAULT_CITY)
    create_element(address, 'City', city_value)
    
    state_value = get_value_with_default(row, 'Mailing State/Province', DEFAULT_STATE)
    standardized_state = standardize_state_name(state_value)
    create_element(address, 'State', standardized_state)
    
    zip_code = get_value_with_default(row, 'Mailing Zip/Postal Code', DEFAULT_ZIP_CODE)
    create_element(address, 'ZipCode', zip_code)
    
    # Country with standardization
    country = create_element(address, 'Country')
    country_value = get_value_with_default(row, 'Mailing Country', DEFAULT_COUNTRY)
    standardized_country = standardize_country_code(country_value)
    create_element(country, 'Code', standardized_country)
    
    # Status fields (optional but recommended)
    create_element(counselor_record, 'VerifiedToBeInBusiness', 'Undetermined')
    
    # Set session type to "Training" for training clients (required)
    create_element(counselor_record, 'SessionType', DEFAULT_SESSION_TYPE)
    
    # Language information (required)
    language = create_element(counselor_record, 'Language')
    create_element(language, 'Code', DEFAULT_LANGUAGE)  
    
    # Date counseled - use Start Date or current date if missing (required)
    date_counseled = format_date(row.get('Start Date', ''))
    if not date_counseled:
        date_counseled = datetime.now().strftime("%Y-%m-%d")
    create_element(counselor_record, 'DateCounseled', date_counseled)
    
    # CHANGE 2: Use "Class Teacher" field instead of "Class/Event Name" for counselor name
    counselor_name_value = get_value_with_default(row, 'Class Teacher', DEFAULT_COUNSELOR_NAME)
    create_element(counselor_record, 'CounselorName', counselor_name_value)
    
    # CHANGE 1: Set all counseling hours to 0
    counseling_hours = create_element(counselor_record, 'CounselingHours')
    create_element(counseling_hours, 'Contact', "0")
    create_element(counseling_hours, 'Prepare', "0")
    create_element(counseling_hours, 'Travel', "0") 
    
    # Basic counseling provided (required)
    counseling_provided = create_element(counselor_record, 'CounselingProvided')
    # Try to get from Nature of the Counseling Seeking, or use default
    counseling_type = get_value_with_default(row, 'Nature of the Counseling Seeking?', DEFAULT_COUNSELING_TYPE)
    create_element(counseling_provided, 'Code', counseling_type)
    
    # Training-specific section (required for training clients)
    training_session = create_element(counselor_record, 'TrainingSession')
    
    # DateTrainingStarted - use the Start Date or current date if missing
    training_date = format_date(row.get('Start Date', ''))
    if not training_date:
        training_date = datetime.now().strftime("%Y-%m-%d")
    create_element(training_session, 'DateTrainingStarted', training_date)
    
    # Partner Training Number - use Class/Event ID or generate one
    create_element(training_session, 'PartnerTrainingNumber', class_id)
    
    # Employees Trained - default to 1 (the attendee)
    create_element(training_session, 'EmployeesTrained', str(DEFAULT_EMPLOYEES_TRAINED))
    
    # Hours Trained - use default value
    create_element(training_session, 'HoursTrained', str(training_hours))

def create_training_xml_from_csv(csv_file_path, xml_file_path, training_hours=DEFAULT_TRAINING_HOURS, logger=None):
    """
    Converts training client data from CSV format to XML.
    
    Args:
        csv_file_path: Path to the input CSV file
        xml_file_path: Path where the output XML file will be saved
        training_hours: Default training hours to assign if not in CSV
        logger: Optional logger instance
    """
    # Logger will be passed in from main()
    
    # Open and read the CSV file
    try:
        with open(csv_file_path, 'r', encoding='utf-8-sig') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            rows = list(csv_reader)
            logger.info(f"Successfully read CSV file with {len(rows)} records")
    except Exception as e:
        logger.error(f"Failed to read CSV file: {str(e)}")
        raise
    
    # Create XML structure
    root = ET.Element('CounselingInformation')
    processed_records = 0
    skipped_records = 0

    # Process each row
    for row_index, row in enumerate(rows, 1):
        # Get record ID for tracking
        record_id = get_value_with_default(row, 'Contact ID', f"Row_{row_index}")
        
        # Generate a record ID if missing
        if record_id == f"Row_{row_index}":
            record_id = f"TRAIN{row_index}"
            logger.warning(f"Generated record ID {record_id} for row {row_index} due to missing Contact ID")
            
        try:
            # Create counseling record element
            counseling_record = create_element(root, 'CounselingRecord')
            
            # Add PartnerClientNumber (required)
            create_element(counseling_record, 'PartnerClientNumber', record_id)
                
            # Location section
            location = create_element(counseling_record, 'Location')
            create_element(location, 'LocationCode', DEFAULT_LOCATION_CODE)  # Use default from .config
            
            # Build ClientRequest section
            build_client_request_section(counseling_record, row, record_id, logger)
            
            # Build ClientIntake section
            build_client_intake_section(counseling_record, row, record_id, logger)
            
            # Build CounselorRecord section with training specifics
            build_training_counselor_record_section(counseling_record, row, record_id, logger, training_hours)
            
            processed_records += 1
            
        except Exception as e:
            logger.error(f"Error processing record {record_id}: {str(e)}")
            skipped_records += 1
                
    # Write the XML tree to the output file
    try:
        tree = ET.ElementTree(root)
        tree.write(xml_file_path, encoding='utf-8', xml_declaration=True)
        logger.info(f"XML file created successfully with {processed_records} records")
        logger.info(f"Skipped {skipped_records} records due to errors")
    except Exception as e:
        logger.error(f"Failed to write XML file: {str(e)}")
        raise

def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description='Training Client CSV to XML Converter')
    parser.add_argument('--input', '-i', required=True, help='Input CSV file')
    parser.add_argument('--output', '-o', help='Output XML file (optional)')
    parser.add_argument('--training-hours', '-t', type=float, default=DEFAULT_TRAINING_HOURS,
                       help=f'Default training hours for each record (default: {DEFAULT_TRAINING_HOURS})')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                        default='INFO', help='Logging level')
    
    args = parser.parse_args()
    
    # Setup logger using ConversionLogger
    from .logging_util import ConversionLogger
    log_level_val = getattr(logging, args.log_level.upper(), logging.INFO)
    # For this script, file logging is not explicitly configured via CLI.
    # Defaulting log_to_file=False for now, or add a --log-file arg if needed.
    logger = ConversionLogger(
        logger_name="TrainingClientXML",
        log_level=log_level_val,
        log_to_file=False 
    ).logger # Get the actual logger instance
    
    # Determine output file path if not specified
    if not args.output:
        input_file = os.path.basename(args.input)
        base_name = os.path.splitext(input_file)[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"{base_name}_training_{timestamp}.xml"
        args.output = output_file
    
    # Process the file
    logger.info(f"Converting training data from {args.input} to {args.output}")
    create_training_xml_from_csv(args.input, args.output, args.training_hours, logger)
    logger.info("Conversion complete")

if __name__ == "__main__":
    main()