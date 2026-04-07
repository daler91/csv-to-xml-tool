"""
Configuration settings for the CSV to XML conversion utility.

This module is structured with classes to group configurations by their domain:
- GeneralConfig: Constants that are shared across multiple converters.
- CounselingConfig: Settings specific to the Counseling (Form 641) report.
- TrainingConfig: Settings specific to the Management Training Report.
- ValidationCategory: Enumeration of validation issue types.
"""
from datetime import date

FISCAL_YEAR_START_MONTH = 10

# Shared date input formats (single source of truth)
DATE_INPUT_FORMATS = [
    '%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y',
    '%m/%d/%y', '%d-%m-%Y',
    '%Y/%m/%d', '%y/%m/%d',
    '%m-%d-%y',
]


def _fiscal_year_start():
    """Compute the start of the current SBA fiscal year (October 1)."""
    today = date.today()
    year = today.year if today.month >= FISCAL_YEAR_START_MONTH else today.year - 1
    return f"{year}-{FISCAL_YEAR_START_MONTH:02d}-01"

# =============================================================================
# GENERAL CONFIGURATION
# =============================================================================
class GeneralConfig:
    """Shared configuration constants."""
    DEFAULT_LOCATION_CODE = "249003"
    DEFAULT_LANGUAGE = "English"
    DEFAULT_BUSINESS_STATUS = "No"

# =============================================================================
# COUNSELING REPORT CONFIGURATION (FORM 641)
# =============================================================================
class CounselingConfig:
    """Configuration specific to the Counseling (Form 641) XML conversion."""
    REQUIRED_FIELDS = ["Contact ID"]

    # Correct XSD element order for ClientIntake section
    CLIENT_INTAKE_ELEMENT_ORDER = [
        'Race', 'Ethnicity', 'Sex', 'Disability', 'MilitaryStatus',
        'BranchOfService', 'Media', 'Internet', 'CurrentlyInBusiness',
        'CurrentlyExporting', 'CompanyName', 'BusinessType',
        'BusinessOwnership', 'ConductingBusinessOnline',
        'ClientIntake_Certified8a', 'Employee_Owned', 'TotalNumberOfEmployees',
        'NumberOfEmployeesInExportingBusiness', 'ClientAnnualIncomePart2',
        'LegalEntity', 'Rural_vs_Urban', 'FIPS_Code', 'CounselingSeeking',
        'ExportCountries'
    ]
    DEFAULT_SESSION_TYPE = "Telephone"
    DEFAULT_URBAN_RURAL = "Undetermined"
    MIN_COUNSELING_DATE = _fiscal_year_start()

    # List of session types that don't require contact hours
    NO_CONTACT_HOUR_SESSION_TYPES = [
        "Prepare Only",
        "Training",
        "Update Only"
    ]

    VALID_SESSION_TYPES = [
        "Face-to-face",
        "Online",
        "Prepare Only",
        "Telephone",
        "Training",
        "Update Only"
    ]

    # Maximum field lengths for truncation
    MAX_FIELD_LENGTHS = {
        "CounselorNotes": 1000,
        "Last": 40,
        "First": 40,
        "Middle": 1,
        "Street1": 80,
        "Street2": 80,
        "City": 80,
        "Phone": 10,
        "PartnerClientNumber": 20,
        "PartnerSessionNumber": 20
    }

# =============================================================================
# TRAINING REPORT CONFIGURATION (MANAGEMENT TRAINING)
# =============================================================================
class TrainingConfig:
    """Configuration specific to the Management Training Report XML conversion."""
    REQUIRED_FIELDS = ["Class/Event ID"]
    DEFAULT_TRAINING_SESSIONS = "1"
    DEFAULT_TRAINING_HOURS = "1.5"
    DEFAULT_TRAINING_EVENT_TITLE_PREFIX = "Training Event "
    DEFAULT_TRAINING_TOPIC = "Technology"
    DEFAULT_PROGRAM_FORMAT = "In-person"
    DEFAULT_TRAINING_PARTNER_CODE = "Women's Business Center"
    DEFAULT_TRAINING_FEES = "0"
    DEFAULT_START_DATE = "2023-12-12"

    # Default location if not found in CSV
    DEFAULT_LOCATION = {
        "city": "Des Moines",
        "state": "Iowa",
        "zip": "50312",
        "country": "United States"
    }

    # Date formats to try when parsing (references the shared list)
    DATE_INPUT_FORMATS = DATE_INPUT_FORMATS

    # Mapping for CSV column names. This allows flexibility if headers change.
    COLUMN_MAPPING = {
        "event_id": "Class/Event ID",
        "event_name": "Class/Event Name",
        "start_date": "Start Date",
        "funding_source": "Funding Source",
        "training_topic": "Training Topic",
        "event_type": "Class/Event Type",
        "cosponsor": ['Cosponsor', 'CosponsorsName', 'Partner Organization'],
        # Location fields (list of possible headers)
        "city": ['City', 'city', 'Address', 'Street Line 1'],
        "state": ['State/Province', 'State', 'state'],
        "zip": ['Zip/Postal Code', 'Zip', 'zip', 'ZipCode', 'Zip code'],
        # Demographic fields
        "business_status": ['Currently in Business?', 'Currently in Business', 'In Business'],
        "gender": ['Gender', 'gender', 'Sex'],
        "disability": ['Disabilities', 'Disability', 'Has Disability'],
        "military_status": ['Military Status', 'Military', 'Veteran Status'],
        "race": ['Race', 'race', 'Racial Background'],
        "ethnicity": ['Ethnicity', 'ethnicity', 'Ethnic Background']
    }

    # Mappings for specific field values
    TRAINING_TOPIC_MAPPINGS = {
        'Technology': 'Technology', 'Tech': 'Technology', 'IT': 'Technology',
        'Marketing': 'Marketing/Sales', 'Sales': 'Marketing/Sales',
        'Start-up': 'Business Start-up/Preplanning', 'Startup': 'Business Start-up/Preplanning',
        'Business Plan': 'Business Plan',
    }

    PROGRAM_FORMAT_MAPPINGS = {
        'Hybrid': 'Hybrid', 'In-person': 'In-person', 'On Demand': 'On Demand', 'Online': 'Online',
        'Seminar': 'In-person', 'Webinar': 'Online', 'Virtual': 'Online', 'Remote': 'Online',
    }

    # Keywords for parsing demographic data from free-text fields
    DEMOGRAPHIC_KEYWORDS = {
        "gender": {
            "female": ['female', 'f', 'woman', 'women'],
            "male": ['male', 'm', 'man', 'men']
        },
        "military": {
            "active_duty": ['active duty', 'active-duty'],
            "veteran": ['veteran'],
            "service_disabled_veteran": ['service disabled', 'disabled vet'],
            "reserve_guard": ['reserve', 'guard'],
            "spouse": ['spouse']
        },
        "race": {
            "asian": ['asian'],
            "black": ['black', 'african american'],
            "native_american": ['american indian', 'alaska native', 'native american'],
            "pacific_islander": ['hawaiian', 'pacific islander'],
            "white": ['white', 'caucasian'],
            "middle_eastern": ['middle east'],
            "north_african": ['north africa']
        },
        "ethnicity": {
            "hispanic": ['hispanic', 'latino'],
            "non_hispanic_keywords": ['non-hispanic'] # This is for explicit non-hispanic values
        }
    }


# =============================================================================
# TRAINING CLIENT CONFIGURATION (FORM 641 - TRAINING CLIENTS)
# =============================================================================
class TrainingClientConfig:
    """Configuration for converting training client CSV data to Form 641 XML.

    Training clients fill out a smaller form with different column names.
    This config maps those columns to the counseling-format columns expected
    by CounselingConverter, and provides defaults for absent fields.
    """

    # Maps training client CSV column names to counseling converter column names
    COLUMN_MAPPING = {
        'Phone': 'Contact: Phone',
        'Company': 'Account Name',
        'Street': 'Mailing Street',
        'city': 'Mailing City',
        'State': 'Mailing State/Province',
        'Zip code': 'Mailing Zip/Postal Code',
        'Disabilities': 'Disability',
        'Military Status': 'Veteran Status',
        'Ethnicity': 'Ethnicity:',
        'Class/Event ID': 'Activity ID',
        'Class Teacher': 'Name of Counselor',
        'Start Date': 'Date',
        'Class/Event Type': 'Type of Session',
        'Currently in Business?': 'Currently In Business?',
    }

    # Default values for counseling columns absent from the training client CSV
    DEFAULTS = {
        'Middle Name': '',
        'Contact: Secondary Phone': '',
        'Mailing Country': 'US',
        'Agree to Impact Survey': 'No',
        'Client Signature - Date': '',
        'Client Signature(On File)': 'No',
        'Branch Of Service': '',
        'What Prompted you to contact us?': '',
        'Internet (specify)': '',
        'InternetUsage': '',
        'Are you currently exporting?(old)': 'No',
        'Type of Business': '',
        'Business Ownership - % Female(old)': '0',
        'Conduct Business Online?': 'No',
        '8(a) Certified?(old)': 'No',
        'Total Number of Employees': '',
        'Number of Employees in Exporting Business': '',
        'Gross Revenues/Sales': '',
        'Profits/Losses': '',
        'Rural_vs_Urban': 'Undetermined',
        'FIPS_Code': '',
        'Nature of the Counseling Seeking?': '',
        'Nature of the Counseling Seeking - Other Detail': '',
        'Legal Entity of Business': '',
        'Other legal entity (specify)': '',
        'Verified To Be In Business': 'Undetermined',
        'Reportable Impact': 'No',
        'Reportable Impact Date': '',
        'Business Start Date': '',
        'Date Started (Meeting)': '',
        'Total No. of Employees (Meeting)': '',
        'Gross Revenues/Sales (Meeting)': '',
        'Profit & Loss (Meeting)': '',
        'SBA Loan Amount': '0',
        'Non-SBA Loan Amount': '0',
        'Amount of Equity Capital Received': '0',
        'Certifications (SDB, HUBZONE, etc)': '',
        'Other Certifications': '',
        'SBA Financial Assistance': '',
        'Other SBA Financial Assistance': '',
        'Services Provided': 'Business Start-up/Preplanning',
        'Other Counseling Provided': '',
        'Referred Client to': '',
        'Other (Referred Client to)': '',
        'Language(s) Used': 'English',
        'Language(s) Used (Other)': '',
        'Duration (hours)': '0',
        'Prep Hours': '0',
        'Travel Hours': '0',
        'Comments': '',
    }


# =============================================================================
# VALIDATION
# =============================================================================
class ValidationCategory:
    """Enumeration of categories for validation issues."""
    MISSING_REQUIRED = "missing_required_field"
    MISSING_FIELD = "missing_field"
    INVALID_FORMAT = "invalid_format"
    INVALID_VALUE = "invalid_value"
    INVALID_DATE = "invalid_date"
    TRUNCATED_VALUE = "truncated_value"
    STANDARDIZED_VALUE = "standardized_value"
    PROCESSING_ERROR = "processing_error"
    FILE_ACCESS = "file_access"
    FILE_WRITE = "file_write"
