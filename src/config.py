"""
Configuration settings for the CSV to XML conversion utility.

This module is structured with classes to group configurations by their domain:
- GeneralConfig: Constants that are shared across multiple converters.
- CounselingConfig: Settings specific to the Counseling (Form 641) report.
- TrainingConfig: Settings specific to the Management Training Report.
- ValidationCategory: Enumeration of validation issue types.
"""
from datetime import date


def _fiscal_year_start():
    """Compute the start of the current SBA fiscal year (October 1)."""
    today = date.today()
    year = today.year if today.month >= 10 else today.year - 1
    return f"{year}-10-01"

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

    # Mapping from CSV headers to a conceptual model. This is not used directly
    # by the new converter but is kept for reference. The new converter will use
    # more specific mappings.
    FIELD_MAPPING = {
        "Contact ID": "PartnerClientNumber",
        "Last Name": "ClientRequest_LastName",
        # ... (rest of the original FIELD_MAPPING can be kept for reference if needed)
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

    # Date formats to try when parsing
    DATE_INPUT_FORMATS = [
        '%Y-%m-%d', '%m/%d/%Y', '%d-%m-%Y', '%m-%d-%Y', '%m/%d/%y'
    ]

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
        'Technology': 'Technology', 'Tech': 'Technology', 'IT': 'Technology', # ... (and so on)
        'Marketing': 'Marketing/Sales', 'Sales': 'Marketing/Sales',
        'Start-up': 'Business Start-up/Preplanning', 'Startup': 'Business Start-up/Preplanning',
        'Business Plan': 'Business Plan',
        # ... (full map from original config)
    }

    PROGRAM_FORMAT_MAPPINGS = {
        'Hybrid': 'Hybrid', 'In-person': 'In-person', 'On Demand': 'On Demand', 'Online': 'Online',
        'Seminar': 'In-person', 'Webinar': 'Online', 'Virtual': 'Online', 'Remote': 'Online',
        # ... (full map from original config)
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
