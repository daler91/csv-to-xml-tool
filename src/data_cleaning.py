  
"""
Enhanced data cleaning and formatting utilities for Salesforce CSV to XML conversion.
This module contains functions for cleaning and standardizing Salesforce data formats.
"""
import re
from datetime import datetime
from .config import CounselingConfig

UNITED_STATES = "United States"
UNITED_KINGDOM = "United Kingdom"

DEFAULT_STATE_MAPPINGS = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
    'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia',
    'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
    'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire',
    'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina',
    'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania',
    'RI': 'Rhode Island', 'SC': 'South Carolina', 'SD': 'South Dakota', 'TN': 'Tennessee',
    'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington',
    'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia',
    'AS': 'American Samoa', 'GU': 'Guam', 'MP': 'Northern Mariana Islands', 'PR': 'Puerto Rico',
    'VI': 'U.S. Virgin Islands'
}

# Default list of valid states, can be overridden by valid_states_list
DEFAULT_VALID_STATES = set(DEFAULT_STATE_MAPPINGS.values()) | {
    "Armed Forces Europe", "Armed Forces Pacific", "Armed Forces the Americas",
    "Federated States of Micronesia", "Marshall Islands", "Republic of Palau",
    "United States Minor Outlying Islands"
}

# Reverse mapping: lowercase full name -> canonical full name
_STATE_NAME_LOOKUP = {name.lower(): name for name in DEFAULT_STATE_MAPPINGS.values()}


def _resolve_state_name(state_str, valid_states_list):
    """Resolve a state string to its canonical name via abbreviation, full name, or valid states lookup."""
    if state_str.lower() == 'd.c.':
        return 'District of Columbia'

    upper = state_str.upper()
    if upper in DEFAULT_STATE_MAPPINGS:
        return DEFAULT_STATE_MAPPINGS[upper]

    lower = state_str.lower()
    if lower in _STATE_NAME_LOOKUP:
        return _STATE_NAME_LOOKUP[lower]

    reference_list = valid_states_list if valid_states_list is not None else DEFAULT_VALID_STATES
    for valid_st in reference_list:
        if lower == valid_st.lower():
            return valid_st

    return state_str


def _case_insensitive_lookup(name, valid_states_list):
    """Find name in valid_states_list case-insensitively. Returns canonical name or None."""
    lower = name.lower()
    for item in valid_states_list:
        if lower == item.lower():
            return item
    return None


def standardize_state_name(state_value, valid_states_list=None, default_return=""):
    """
    Standardizes state codes/names. Converts abbreviations to full names,
    validates against an optional list, and handles various formats.

    Args:
        state_value: State name or code.
        valid_states_list: Optional list/set of valid state names. If provided,
                           the standardized name must be in this list.
        default_return: Value to return if input is empty, unstandardizable,
                        or not in valid_states_list (if provided).

    Returns:
        Standardized and validated state name, or default_return.
    """
    if not state_value or str(state_value).strip() == "" or str(state_value).lower() == "nan":
        return default_return

    state_str = str(state_value).strip()
    standardized_name = _resolve_state_name(state_str, valid_states_list)

    if not standardized_name:
        return default_return

    if valid_states_list is not None and standardized_name not in valid_states_list:
        match = _case_insensitive_lookup(standardized_name, valid_states_list)
        return match if match else default_return

    return standardized_name

def map_value(value, mapping_dict, default_value, case_sensitive=False):
    """
    Maps an input value using a dictionary, with options for case sensitivity
    and a default return value.

    Args:
        value: The input value to map.
        mapping_dict: A dictionary where keys are input values and values are
                      the mapped output values.
        default_value: The value to return if the input value is not found
                       in mapping_dict or if value is None/empty.
        case_sensitive: Boolean, if False (default), perform case-insensitive
                        matching for keys in mapping_dict.

    Returns:
        The mapped value or default_value.
    """
    if value is None:
        return default_value
    
    value_str = str(value).strip()
    if not value_str: # Handles empty string and strings that become empty after strip
        return default_value

    if not case_sensitive:
        # Iterate through dict keys for case-insensitive comparison
        for k, v in mapping_dict.items():
            if str(k).lower() == value_str.lower():
                return v
        # If no case-insensitive match, proceed to return default_value
    else:
        # Case-sensitive lookup
        if value_str in mapping_dict:
            return mapping_dict[value_str]
        # Check if original value (if not string) is in mapping_dict
        elif value in mapping_dict:
             return mapping_dict[value]


    return default_value

def standardize_country_code(country):
    """
    Standardizes country codes to ensure they match the required format in XSD.
    Handles various forms of country codes including "US", "USA", etc.

    Args:
        country: Country name or code

    Returns:
        Standardized country name
    """
    if not country or str(country).strip() == "" or str(country).lower() == "nan":
        return UNITED_STATES  # Default to United States if empty

    country_upper = str(country).strip().upper()

    country_map = {
        "US": UNITED_STATES,
        "USA": UNITED_STATES,
        "U.S.": UNITED_STATES,
        "U.S.A.": UNITED_STATES,
        "UNITED STATES": UNITED_STATES,
        "UNITED STATES OF AMERICA": UNITED_STATES,
        "AMERICA": UNITED_STATES,
        "CA": "Canada",
        "CAN": "Canada",
        "MX": "Mexico",
        "MEX": "Mexico",
        "UK": UNITED_KINGDOM,
        "GB": UNITED_KINGDOM,
        "GBR": UNITED_KINGDOM,
        "GREAT BRITAIN": UNITED_KINGDOM,
        "ENGLAND": UNITED_KINGDOM,
    }

    return country_map.get(country_upper, str(country).strip())

def clean_phone_number(phone):
    """
    Removes all non-numeric characters from a phone number and normalizes to 10 digits.
    Strips leading country code '1' from 11-digit numbers.
    Returns empty string if phone is None or empty.

    Examples:
        "(123) 456-7890" -> "1234567890"
        "123.456.7890" -> "1234567890"
        "+1 (123) 456-7890" -> "1234567890"
    """
    if not phone or str(phone).strip() == "" or str(phone).lower() == "nan":
        return ""

    digits = ''.join(char for char in str(phone) if char.isdigit())
    # Strip leading US country code
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    return digits[:10]

def format_date(date_str, input_formats=None, default_return=""):
    """
    Converts date from various formats to YYYY-MM-DD format.
    Returns default_return if date_str is empty, None, or cannot be parsed.
    
    Args:
        date_str: The date string to parse.
        input_formats: Optional list of strptime formats to try.
                       If None, uses a default list.
        default_return: Value to return if parsing fails or input is empty.
    """
    if not date_str or str(date_str).strip() == "" or str(date_str).lower() == "nan":
        return default_return

    date_str = str(date_str).strip()

    if input_formats is None or not input_formats:
        # Default list of formats, similar to what was in classDataConverter.py
        # and data_cleaning.py (implicitly)
        input_formats = [
            '%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y', 
            '%m/%d/%y', '%d-%m-%Y', # Added %d-%m-%Y from classDataConverter
            # The following are variations to catch common cases if year is 2 digits
            '%Y/%m/%d', '%y/%m/%d', 
            '%m-%d-%y', 
        ]

    for fmt in input_formats:
        try:
            dt_object = datetime.strptime(date_str, fmt)
            return dt_object.strftime('%Y-%m-%d')
        except ValueError:
            continue

    return default_return

def clean_whitespace(text):
    """
    Cleans excess whitespace from text while preserving normal spacing between words and sentences.
    - Replaces multiple spaces with a single space
    - Removes leading/trailing whitespace
    - Preserves single newlines but removes extras
    - Handles Salesforce-specific patterns
    """
    if not text or str(text).strip() == "" or str(text).lower() == "nan":
        return ""
        
    # Convert to string explicitly
    text = str(text)
    
    # Split on newlines and handle each line
    lines = text.split('\n')
    cleaned_lines = []
    
    for line in lines:
        # Remove leading/trailing whitespace from each line
        line = line.strip()
        # Replace multiple spaces with single space
        line = ' '.join(line.split())
        # Remove Salesforce-specific artifacts
        line = re.sub(r'\[\w+\]:', '', line)  # Removes things like [User]: 
        if line:  # Only add non-empty lines
            cleaned_lines.append(line)
    
    # Join with single newlines
    return '\n'.join(cleaned_lines)

def map_gender_to_sex(gender_value):
    """
    Maps various gender values to just 'Female' or 'Male' per XSD requirements.
    Returns empty string if no match or missing.
    """
    if not gender_value or str(gender_value).strip() == "" or str(gender_value).lower() == "nan":
        return ""
    
    gender_str = str(gender_value).lower()
    
    if "female" in gender_str:
        return "Female"
    elif "male" in gender_str and "female" not in gender_str:  # Handle edge case for "Female" containing "male"
        return "Male"
    
    # Return empty string for any other values like "Non-binary", "Prefer not to say", etc.
    return ""

def split_multi_value(value, delimiter=";"):
    """
    Splits multi-value fields with the specified delimiter.
    Returns an empty list if the value is empty or None.
    """
    if not value or str(value).strip() == "" or str(value).lower() == "nan":
        return []
    
    return [item.strip() for item in str(value).split(delimiter) if item.strip()]

def clean_numeric(value):
    """
    Cleans a numeric string by removing commas, currency symbols, and whitespace.
    Extracts digits and optional decimal point.
    """
    if value is None or str(value).strip() == "" or str(value).strip().lower() == "nan":
        return ""
    
    cleaned_str = str(value).replace(" ", "").replace("$", "").replace(",", "")

    try:
        float_val = float(cleaned_str)
        if float_val.is_integer():
            return str(int(float_val))
        return str(float_val)
    except (ValueError, TypeError):
        return ""

def clean_percentage(value):
    """
    Cleans a percentage string, removing the % symbol and converting to a decimal.
    Returns a number between 0 and 100.
    """
    if not value or str(value).strip() == "" or str(value).lower() == "nan":
        return "0"
    
    value_str = str(value).strip()
    if value_str.endswith('%'):
        value_str = value_str[:-1].strip()

    try:
        float_val = float(value_str)
        # Ensure it's between 0 and 100
        float_val = float(max(0, min(100, float_val)))

        if float_val.is_integer():
            return str(int(float_val))

        return str(float_val)
    except (ValueError, TypeError):
        return "0"

def truncate_counselor_notes(notes, max_length=CounselingConfig.MAX_FIELD_LENGTHS["CounselorNotes"]):
    """
    Cleans counselor notes and ensures they don't exceed the maximum length.
    If notes exceed max_length, they are truncated at a sentence or word boundary.
    
    Args:
        notes: The counselor notes text
        max_length: Maximum allowed length (default from config)
        
    Returns:
        Cleaned and truncated notes
    """
    # First clean the whitespace
    cleaned_notes = clean_whitespace(notes)
    
    # If already within limit, return as is
    if len(cleaned_notes) <= max_length:
        return cleaned_notes
    
    # Try to truncate at a sentence boundary
    truncated = cleaned_notes[:max_length]
    
    # Look for last sentence boundary within the limit
    sentence_boundaries = ['.', '!', '?', '\n']
    last_boundary_pos = -1
    
    for boundary in sentence_boundaries:
        pos = truncated.rfind(boundary)
        if pos > last_boundary_pos:
            last_boundary_pos = pos
    
    # If found a sentence boundary, truncate there
    if last_boundary_pos > 0:
        return cleaned_notes[:last_boundary_pos + 1]
    
    # Otherwise try to truncate at a word boundary
    last_space = truncated.rfind(' ')
    if last_space > 0:
        return cleaned_notes[:last_space]
    
    # If all else fails just truncate at max_length
    return truncated