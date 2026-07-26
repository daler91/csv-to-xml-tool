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

# Delimiter for Salesforce multi-select picklist exports (e.g. "Race", "Services
# Provided"): Salesforce joins multi-value fields with a semicolon, and the
# individual code values are controlled vocabulary assumed not to contain ';'.
# Centralized here (CONV-5); split_multi_value() also accepts a per-call override.
MULTI_VALUE_DELIMITER = ";"

# Default "Services Provided" / training-topic value from the SBA controlled
# vocabulary. Centralized so the literal isn't repeated across the mappings,
# the defaults table and the converters (Sonar S1192).
BUSINESS_STARTUP_PREPLANNING = "Business Start-up/Preplanning"


def fiscal_year_start():
    """Start of the *current* SBA fiscal year (October 1), as YYYY-MM-DD.

    Call this rather than caching the result. It used to be frozen into
    CounselingConfig.MIN_COUNSELING_DATE at import time, so a long-lived
    process (the worker is a persistent service) kept the previous fiscal
    year's cutoff after October 1 and stopped flagging dates it should have.
    """
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

# Valid FundingSource values from the XSD enumeration (disaster/program codes).
# FundingSource is optional (minOccurs=0); a value that is NOT one of these
# (e.g. a WBC "CORE"/"Federal" funding label) must be omitted, not emitted, or
# the XML fails schema validation. Emitted verbatim when matched case-insensitively.
VALID_FUNDING_SOURCES = [
    "2020 SBDC Portable Assistance – PA2003",
    "2023 Portable Assistance - PA2023",
    "2024 SBDC Supplemental Program - SP2024",
    "Hurricane Dolly (TX) – 1780",
    "Hurricane Gustav (LA) – 1786",
    "Hurricane Gustav (MS) – 1794",
    "Hurricane Ike (LA) – 1792",
    "Hurricane Ike (TX) – 1791",
    "Hurricane Sandy - Phase 1 – SANDY1",
    "Hurricane Sandy - Phase 2 – SANDY2",
    "Resiliency and Recovery Demonstration Grant – CARESRRD",
    "Severe Storms, and Flooding (GA) – 1761",
    "Severe Storms, and Flooding (IL) – 1747",
    "Severe Storms, and Flooding (IL) – 1771",
    "Severe Storms, and Flooding (IL) – 1800",
    "Severe Storms, and Flooding (IN) – 1795",
    "Severe Storms, and Flooding (IN) – 1766",
    "Severe Storms, and Flooding (MO) – 1749",
    "Severe Storms, and Flooding (MO) – 1773",
    "Severe Storms, and Flooding (MS) – 1753",
    "Severe Storms, and Flooding (PR) – 1798",
    "Severe Storms, and Flooding, Tornadoes (MO) – 1809",
    "Severe Storms, and Tornadoes (CO) – 1762",
    "Severe Storms, and Tornadoes (GA) – 1750",
    "Severe Storms, and Tornadoes (MO) – 1760",
    "Severe Storms, and Tornadoes (MS) – 1764",
    "Severe Storms, Tornadoes, and Flooding (AR) – 1744",
    "Severe Storms, Tornadoes, and Flooding (AR) – 1751",
    "Severe Storms, Tornadoes, and Flooding (AR) – 1758",
    "Severe Storms, Tornadoes, and Flooding (IA) – 1763",
    "Severe Storms, Tornadoes, and Flooding (NE) – 1770",
    "Severe Storms, Tornadoes, and Flooding (WI) – 1768",
    "Severe Storms, Tornadoes, Flooding, Mudslides, and Landslides (WV) – 1769",
    "Severe Storms, Tornadoes, Straight Line Winds, and Flooding (KY) – 1746",
    "Severe Storms, Tornadoes, Straight Line Winds, and Flooding (TN) – 1745",
    "Severe Winter Storm and Flooding (IN) – 1740",
    "Severe Winter Storm and Flooding (NV) – 1738",
    "Tropical Storm Fay (FL) – 1785",
    "Wildfires (CA) – 1810",
]


# =============================================================================
# COUNSELING REPORT CONFIGURATION (FORM 641)
# =============================================================================
class CounselingConfig:
    """Configuration specific to the Counseling (Form 641) XML conversion."""
    REQUIRED_FIELDS = ["Contact ID"]

    # Every CSV header the counseling converter reads, keyed by a stable internal
    # name. This is the single source for the counseling header vocabulary:
    # preview_service's expected-column list, xsd_error_mapping's element->field
    # table and diff_service's cleaning map are all checked against it, and
    # tests/test_expected_columns.py pins it against the converter source itself.
    #
    # Those lists were previously four hand-maintained mirrors that had already
    # disagreed: three columns drifted to a spelling without the "(old)" suffix,
    # which made the mapping page offer a rename that deleted a column the
    # converter needed.
    #
    # A value is either a header string, or a list for the four Part 3 impact
    # fields that fall back to their intake counterpart when the "(Meeting)"
    # column is blank (see _first_present in counseling_converter.py).
    #
    # NOTE: unlike TrainingConfig.COLUMN_MAPPING, a list here is NOT a set of
    # aliases for one column -- 'Total Number of Employees', 'Gross Revenues/Sales'
    # and 'Profits/Losses' are each *also* read on their own as the intake
    # snapshot. Deriving expected columns by taking only the first entry, the way
    # the training derivation does, would silently drop three real columns and
    # recreate the drift bug. Use expected_columns() below, which unions them.
    COLUMN_MAPPING = {
        # Identity and contact
        "contact_id": 'Contact ID',
        "location_code": 'LocationCode',
        "last_name": 'Last Name',
        "first_name": 'First Name',
        "middle_name": 'Middle Name',
        "email": 'Email',
        "contact_phone": 'Contact: Phone',
        "contact_secondary_phone": 'Contact: Secondary Phone',
        "mailing_street": 'Mailing Street',
        "mailing_city": 'Mailing City',
        "mailing_state_province": 'Mailing State/Province',
        "mailing_zip_postal_code": 'Mailing Zip/Postal Code',
        "mailing_country": 'Mailing Country',
        "agree_to_impact_survey": 'Agree to Impact Survey',
        "client_signature_date": 'Client Signature - Date',
        "client_signature_on_file": 'Client Signature(On File)',
        # Demographics
        "race": 'Race',
        "ethnicity": 'Ethnicity:',          # trailing colon is in the real CSV header
        "gender": 'Gender',
        "disability": 'Disability',
        "veteran_status": 'Veteran Status',
        "branch_of_service": 'Branch Of Service',
        "what_prompted_contact": 'What Prompted you to contact us?',
        "internet_specify": 'Internet (specify)',
        "internet_usage": 'InternetUsage',
        # Business profile (intake snapshot)
        "currently_in_business": 'Currently In Business?',
        "currently_exporting": 'Are you currently exporting?(old)',
        "account_name": 'Account Name',
        "type_of_business": 'Type of Business',
        "business_ownership_female": 'Business Ownership - % Female(old)',
        "conduct_business_online": 'Conduct Business Online?',
        "certified_8a": '8(a) Certified?(old)',
        "employee_owned": 'Employee Owned',
        "total_employees_intake": 'Total Number of Employees',
        "employees_in_exporting_business": 'Number of Employees in Exporting Business',
        "gross_revenues_intake": 'Gross Revenues/Sales',
        "profits_losses_intake": 'Profits/Losses',
        "legal_entity": 'Legal Entity of Business',
        "other_legal_entity": 'Other legal entity (specify)',
        "rural_vs_urban": 'Rural_vs_Urban',
        "fips_code": 'FIPS_Code',
        "counseling_seeking": 'Nature of the Counseling Seeking?',
        "counseling_seeking_other": 'Nature of the Counseling Seeking - Other Detail',
        "export_countries": 'Export Countries',
        # Session / activity
        "activity_id": 'Activity ID',
        "funding_source": 'Funding Source',
        "verified_in_business": 'Verified To Be In Business',
        "reportable_impact": 'Reportable Impact',
        "reportable_impact_date": 'Reportable Impact Date',
        # Part 3 impact -- each falls back to its intake counterpart when blank
        "business_start_date": ['Business Start Date', 'Date Started (Meeting)'],
        "total_employees_part3": ['Total No. of Employees (Meeting)', 'Total Number of Employees'],
        "gross_revenues_part3": ['Gross Revenues/Sales (Meeting)', 'Gross Revenues/Sales'],
        "profit_loss_part3": ['Profit & Loss (Meeting)', 'Profits/Losses'],
        "sba_loan_amount": 'SBA Loan Amount',
        "non_sba_loan_amount": 'Non-SBA Loan Amount',
        "equity_capital_received": 'Amount of Equity Capital Received',
        "certifications": 'Certifications (SDB, HUBZONE, etc)',
        "other_certifications": 'Other Certifications',
        "sba_financial_assistance": 'SBA Financial Assistance',
        "other_sba_financial_assistance": 'Other SBA Financial Assistance',
        # Counseling delivered
        "services_provided": 'Services Provided',
        "other_counseling_provided": 'Other Counseling Provided',
        "referred_client_to": 'Referred Client to',
        "other_referred_client_to": 'Other (Referred Client to)',
        "type_of_session": 'Type of Session',
        "languages_used": 'Language(s) Used',
        "languages_used_other": 'Language(s) Used (Other)',
        "session_date": 'Date',
        "name_of_counselor": 'Name of Counselor',
        "duration_hours": 'Duration (hours)',
        "prep_hours": 'Prep Hours',
        "travel_hours": 'Travel Hours',
        "comments": 'Comments',
    }

    @classmethod
    def expected_columns(cls) -> list[str]:
        """Every header in COLUMN_MAPPING, de-duplicated, declaration order kept.

        Unions the fallback lists rather than taking the first entry: the
        fallbacks are real columns read elsewhere in their own right, so
        dropping them would report a user's genuine column as "extra" and offer
        a rename that deletes it.
        """
        headers: list[str] = []
        for value in cls.COLUMN_MAPPING.values():
            for header in ([value] if isinstance(value, str) else value):
                if header not in headers:
                    headers.append(header)
        return headers

    @classmethod
    def headers_for(cls, key: str) -> list[str]:
        """The header(s) for one mapping key, in fallback order."""
        value = cls.COLUMN_MAPPING[key]
        return [value] if isinstance(value, str) else list(value)

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
    # No MIN_COUNSELING_DATE constant: call config.fiscal_year_start() so the
    # cutoff follows the calendar instead of the process start time.

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

# Columns the counseling converter defaults to a *non-empty* value when the cell
# is blank (or the column absent) -- i.e. it fabricates data that ships in the
# federal XML. Maps the exact CSV header the converter reads to the default it
# emits. This is the canonical copy, shared by the converters (per-row
# FABRICATED_DEFAULT warnings) and the worker's column_requirements module
# (file-level missing-column warnings).
# The "(Meeting)" revenue/profit variants are intentionally excluded: the
# converter falls back to the base "Gross Revenues/Sales" / "Profits/Losses"
# columns (already listed), so warning on the variants too would just be noise.
COUNSELING_FABRICATION_DEFAULTS = {
    "Gross Revenues/Sales": "0",
    "Profits/Losses": "0",
    "SBA Loan Amount": "0",
    "Non-SBA Loan Amount": "0",
    "Amount of Equity Capital Received": "0",
    "Business Ownership - % Female(old)": "0",
    "Mailing Country": "United States",
    "Conduct Business Online?": "No",
    "8(a) Certified?(old)": "No",
}

# Valid ExportCountries/Code values, in XSD order. Mirrors the enumeration of
# the anonymous simpleType on the "Code" element inside the "ExportCountryList"
# complexType of schemas/SBA_NEXUS_Counseling-2-14.xsd. Any Code value not
# exactly in this list fails schema validation for the whole document, so the
# counseling converter only ever emits these canonical spellings (see the
# drift-guard test in tests/test_integration_xsd.py).
EXPORT_COUNTRY_CODES = (
    "United States",
    "Canada",
    "Mexico",
    "Afghanistan",
    "Aland Islands",
    "Albania",
    "Algeria",
    "Andorra",
    "Angola",
    "Anguilla",
    "Antarctica",
    "Antigua and Barbuda",
    "Argentina",
    "Armenia",
    "Aruba",
    "Australia",
    "Austria",
    "Azerbaijan",
    "Bahamas",
    "Bahrain",
    "Bangladesh",
    "Barbados",
    "Belarus",
    "Belgium",
    "Belize",
    "Benin",
    "Bermuda",
    "Bhutan",
    "Bolivia, Plurinational State of",
    "Bonaire, Sint Eustatius, and Saba",
    "Bosnia and Herzegovina",
    "Botswana",
    "Bouvet Island",
    "Brazil",
    "British Indian Ocean Territory",
    "Brunei Darussalam",
    "Bulgaria",
    "Burkina Faso",
    "Burundi",
    "Cambodia",
    "Cameroon",
    "Cape Verde",
    "Cayman Islands",
    "Central African Republic",
    "Chad",
    "Chile",
    "China",
    "Christmas Island",
    "Cocos (Keeling) Islands",
    "Colombia",
    "Comoros",
    "Congo",
    "Congo, the Democratic Republic of the",
    "Cook Islands",
    "Costa Rica",
    "Cote d’Ivoire",
    "Croatia",
    "Cuba",
    "Curaçao",
    "Cyprus",
    "Czechia",
    "Denmark",
    "Djibouti",
    "Dominica",
    "Dominican Republic",
    "Ecuador",
    "Egypt",
    "El Salvador",
    "Equatorial Guinea",
    "Eritrea",
    "Estonia",
    "Eswatini",
    "Ethiopia",
    "Falkland Islands (Malvinas)",
    "Faroe Islands",
    "Fiji",
    "Finland",
    "France",
    "French Guiana",
    "French Polynesia",
    "French Southern Territories",
    "Gabon",
    "Gambia",
    "Georgia",
    "Germany",
    "Ghana",
    "Gibraltar",
    "Greece",
    "Greenland",
    "Grenada",
    "Guadeloupe",
    "Guatemala",
    "Guernsey",
    "Guinea",
    "Guinea-Bissau",
    "Guyana",
    "Haiti",
    "Heard Island and McDonald Islands",
    "Holy See (Vatican City State)",
    "Honduras",
    "Hungary",
    "Iceland",
    "India",
    "Indonesia",
    "Iran, Islamic Republic of",
    "Iraq",
    "Ireland",
    "Isle of Man",
    "Israel",
    "Italy",
    "Jamaica",
    "Japan",
    "Jersey",
    "Jordan",
    "Kazakhstan",
    "Kenya",
    "Kiribati",
    "Korea, Democratic People’s Republic of",
    "Korea, Republic of",
    "Kosovo",
    "Kuwait",
    "Kyrgyzstan",
    "Lao People’s Democratic Republic",
    "Latvia",
    "Lebanon",
    "Lesotho",
    "Liberia",
    "Libya",
    "Liechtenstein",
    "Lithuania",
    "Luxembourg",
    "Macao",
    "Madagascar",
    "Malawi",
    "Malaysia",
    "Maldives",
    "Mali",
    "Malta",
    "Martinique",
    "Mauritania",
    "Mauritius",
    "Mayotte",
    "Moldova, Republic of",
    "Monaco",
    "Mongolia",
    "Montenegro",
    "Montserrat",
    "Morocco",
    "Mozambique",
    "Myanmar",
    "Namibia",
    "Nauru",
    "Nepal",
    "Netherlands",
    "New Caledonia",
    "New Zealand",
    "Nicaragua",
    "Niger",
    "Nigeria",
    "Niue",
    "Norfolk Island",
    "North Macedonia",
    "Norway",
    "Oman",
    "Pakistan",
    "Palestine",
    "Panama",
    "Papua New Guinea",
    "Paraguay",
    "Peru",
    "Philippines",
    "Pitcairn",
    "Poland",
    "Portugal",
    "Qatar",
    "Reunion",
    "Romania",
    "Russian Federation",
    "Rwanda",
    "Saint Barthélemy",
    "Saint Helena, Ascension and Tristan da Cunha",
    "Saint Kitts and Nevis",
    "Saint Lucia",
    "Saint Martin (French part)",
    "Saint Pierre and Miquelon",
    "Saint Vincent and the Grenadines",
    "Samoa",
    "San Marino",
    "Sao Tome and Principe",
    "Saudi Arabia",
    "Senegal",
    "Serbia",
    "Seychelles",
    "Sierra Leone",
    "Singapore",
    "Sint Maarten (Dutch part)",
    "Slovakia",
    "Slovenia",
    "Solomon Islands",
    "Somalia",
    "South Africa",
    "South Georgia and the South Sandwich Islands",
    "South Sudan",
    "Spain",
    "Sri Lanka",
    "Sudan",
    "Suriname",
    "Svalbard and Jan Mayen",
    "Sweden",
    "Switzerland",
    "Syrian Arab Republic",
    "Taiwan",
    "Tajikistan",
    "Tanzania, United Republic of",
    "Thailand",
    "Timor-Leste",
    "Togo",
    "Tokelau",
    "Tonga",
    "Trinidad and Tobago",
    "Tunisia",
    "Türkiye",
    "Turkmenistan",
    "Turks and Caicos Islands",
    "Tuvalu",
    "Uganda",
    "Ukraine",
    "United Arab Emirates",
    "United Kingdom",
    "Uruguay",
    "Uzbekistan",
    "Vanuatu",
    "Venezuela, Bolivarian Republic of",
    "Vietnam",
    "Virgin Islands, British",
    "Wallis and Futuna",
    "Western Sahara",
    "Yemen",
    "Zambia",
    "Zimbabwe",
    "Other",
)

# Case-insensitive lookup from a lowercased country value to its canonical XSD
# enumeration spelling (e.g. "united kingdom" -> "United Kingdom").
EXPORT_COUNTRY_LOOKUP = {code.lower(): code for code in EXPORT_COUNTRY_CODES}

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
        'Start-up': BUSINESS_STARTUP_PREPLANNING, 'Startup': BUSINESS_STARTUP_PREPLANNING,
        'Business Plan': 'Business Plan',
    }

    PROGRAM_FORMAT_MAPPINGS = {
        'Hybrid': 'Hybrid', 'In-person': 'In-person', 'On Demand': 'On Demand', 'Online': 'Online',
        'Seminar': 'In-person', 'Webinar': 'Online', 'Virtual': 'Online', 'Remote': 'Online',
    }

    # Valid TrainingTopic/Code values from the XSD enumeration. A CSV value that
    # already matches one of these (case-insensitive) is emitted verbatim so a
    # populated "Training Topic" column is authoritative instead of being
    # overwritten by the default. TRAINING_TOPIC_MAPPINGS only adds synonyms.
    VALID_TRAINING_TOPICS = [
        "Business Accounting/Budget", "Business Financial/Cash Flow",
        "Business Financing/Capital Sources", "Business Operations/Management",
        "Business Plan", "Business Start-up/Preplanning", "Buy/Sell Business",
        "Credit Counseling", "Customer Relations", "Cyber Security/Cyber Awareness",
        "Disaster Planning/Recovery", "eCommerce", "Franchising",
        "Government Contracting", "Human Resources/Managing Employees",
        "Intellectual Property Training", "International Trade", "Legal Issues",
        "Marketing/Sales", "Tax Planning", "Technology", "Other",
    ]

    # Shared with the counseling converter; see module-level VALID_FUNDING_SOURCES.
    VALID_FUNDING_SOURCES = VALID_FUNDING_SOURCES

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
        'Currently in Business?': 'Currently In Business?',
    }

    # TrainingSession values: each CSV row is one attendee, so one person is
    # trained per record, and hours trained are a fixed per-session value.
    EMPLOYEES_TRAINED = '1'
    HOURS_TRAINED = '1.5'

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
        'Services Provided': BUSINESS_STARTUP_PREPLANNING,
        'Other Counseling Provided': '',
        'Referred Client to': '',
        'Other (Referred Client to)': '',
        'Language(s) Used': 'English',
        'Language(s) Used (Other)': '',
        # Every training-member record is a Training session ('Class/Event Type'
        # values like 'In-Person' are not valid Form 641 session types). Training
        # is in NO_CONTACT_HOUR_SESSION_TYPES, so contact hours also stay 0.
        'Type of Session': 'Training',
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
    AMBIGUOUS_DATE = "ambiguous_date"
    CLAMPED_VALUE = "clamped_value"
    FABRICATED_DEFAULT = "fabricated_default"
    # An explicitly provided value was overridden because the form doesn't
    # collect the supporting data it requires (vs FABRICATED_DEFAULT, which
    # covers a blank cell replaced by a default).
    DOWNGRADED_VALUE = "downgraded_value"
