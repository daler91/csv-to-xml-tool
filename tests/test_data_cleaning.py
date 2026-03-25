import unittest
from datetime import datetime # For testing date outputs if needed, though format_date handles strings
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data_cleaning import format_date, standardize_state_name, map_value, clean_percentage, truncate_counselor_notes

class TestFormatDate(unittest.TestCase):

    def test_format_date_valid_various_formats(self):
        self.assertEqual(format_date("2023-10-26"), "2023-10-26")
        self.assertEqual(format_date("10/26/2023"), "2023-10-26")
        self.assertEqual(format_date("10-26-2023"), "2023-10-26")
        self.assertEqual(format_date("10/26/23"), "2023-10-26")
        self.assertEqual(format_date("2023/10/26"), "2023-10-26") # Added based on default formats
        self.assertEqual(format_date("23/10/26", input_formats=['%y/%m/%d']), "2023-10-26") # Test specific format

    def test_format_date_custom_input_formats(self):
        self.assertEqual(format_date("26.10.2023", input_formats=["%d.%m.%Y"]), "2023-10-26")
        self.assertEqual(format_date("20231026", input_formats=["%Y%m%d"]), "2023-10-26")
        # Test with a list, first one fails, second one passes
        self.assertEqual(format_date("26/Oct/2023", input_formats=["%d/%m/%Y", "%d/%b/%Y"]), "2023-10-26")

    def test_format_date_invalid_strings(self):
        self.assertEqual(format_date("invalid-date"), "") # Default default_return
        self.assertEqual(format_date("2023-13-01"), "") # Invalid month
        self.assertEqual(format_date("10/32/2023"), "") # Invalid day
        self.assertEqual(format_date("20231026", input_formats=["%d-%m-%Y"]), "") # Mismatch format

    def test_format_date_empty_and_none_input(self):
        self.assertEqual(format_date(""), "")
        self.assertEqual(format_date(None), "")
        self.assertEqual(format_date("   "), "") # Whitespace only
        self.assertEqual(format_date("", default_return="N/A"), "N/A")
        self.assertEqual(format_date(None, default_return="MISSING"), "MISSING")

    def test_format_date_output_format_and_default(self):
        self.assertEqual(format_date("1/1/2023"), "2023-01-01") # Check zero padding
        self.assertEqual(format_date("2023-1-1"), "2023-01-01") # Check zero padding
        self.assertEqual(format_date("bad", default_return="---"), "---")

    def test_format_date_value_error_path(self):
        # Specifically malformed date string that causes ValueError inside the date parsing loop
        # and tests that it continues to try the next format
        self.assertEqual(format_date("10/26/2023", input_formats=["%Y-%m-%d", "%m/%d/%Y"]), "2023-10-26")

        # Test a date that raises ValueError for logical reasons (e.g., Feb 29 on non-leap year)
        self.assertEqual(format_date("2023-02-29", input_formats=["%Y-%m-%d"]), "")

        # Test a date that raises ValueError for the first format but succeeds on the second
        # (leap year case)
        self.assertEqual(format_date("2024-02-29", input_formats=["%m/%d/%Y", "%Y-%m-%d"]), "2024-02-29")

        # Test complete exhaustion of formats due to ValueError
        self.assertEqual(format_date("2023-13-01", input_formats=["%Y-%m-%d", "%m/%d/%Y"]), "")

    def test_format_date_regex_fallback(self):
        # Test the regex fallback logic for missing zero-padding
        self.assertEqual(format_date("2023-1-1", input_formats=["%Y/%m/%d"]), "2023-01-01")
        # Test the regex fallback failing due to invalid date elements
        self.assertEqual(format_date("2023-30-30", input_formats=["%Y/%m/%d"]), "")

class TestStandardizeStateName(unittest.TestCase):
    # Using DEFAULT_VALID_STATES from data_cleaning for some tests
    # These are the states the function itself knows about if no list is passed
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
    DEFAULT_VALID_STATES_LIST = set(DEFAULT_STATE_MAPPINGS.values()) | {
        "Armed Forces Europe", "Armed Forces Pacific", "Armed Forces the Americas",
        "Federated States of Micronesia", "Marshall Islands", "Republic of Palau",
        "United States Minor Outlying Islands"
    }


    def test_standardize_state_abbreviations_and_names_mixed_case(self):
        self.assertEqual(standardize_state_name("AL"), "Alabama")
        self.assertEqual(standardize_state_name("al"), "Alabama")
        self.assertEqual(standardize_state_name("Alabama"), "Alabama")
        self.assertEqual(standardize_state_name("alabama"), "Alabama")
        self.assertEqual(standardize_state_name(" Al "), "Alabama")
        self.assertEqual(standardize_state_name("iOwA"), "Iowa")
        self.assertEqual(standardize_state_name("District of Columbia"), "District of Columbia")
        self.assertEqual(standardize_state_name("d.c."), "District of Columbia") # Assuming 'd.c.' maps to DC

    def test_standardize_state_invalid_names(self):
        # The function should return the original string if it can't be mapped.
        self.assertEqual(standardize_state_name("UnknownState"), "UnknownState")
        self.assertEqual(standardize_state_name("XX"), "XX")
        self.assertEqual(standardize_state_name("Not A State"), "Not A State")

    def test_standardize_state_empty_and_none(self):
        self.assertEqual(standardize_state_name(""), "")
        self.assertEqual(standardize_state_name(None), "")
        self.assertEqual(standardize_state_name("   "), "")
        self.assertEqual(standardize_state_name("", default_return="EMPTY"), "EMPTY")

    def test_standardize_state_with_valid_states_list_pass(self):
        valid_list = {"California", "New York", "Texas"}
        self.assertEqual(standardize_state_name("CA", valid_states_list=valid_list), "California")
        self.assertEqual(standardize_state_name("New York", valid_states_list=valid_list), "New York")
        self.assertEqual(standardize_state_name("texas", valid_states_list=valid_list), "Texas")

    def test_standardize_state_with_valid_states_list_fail(self):
        valid_list = {"California", "New York", "Texas"}
        # Standardizes to "Florida", but "Florida" is not in valid_list
        self.assertEqual(standardize_state_name("FL", valid_states_list=valid_list, default_return="NOT_VALID"), "NOT_VALID")
        # "Unknown" is not in any mapping, and not in valid_list
        self.assertEqual(standardize_state_name("Unknown", valid_states_list=valid_list, default_return="NOT_VALID"), "NOT_VALID")
        # Standardizes to "Alabama", then checks against valid_list. "Alabama" is not in valid_list.
        self.assertEqual(standardize_state_name("al", valid_states_list=valid_list, default_return="FAIL"), "FAIL")


    def test_standardize_state_honors_default_return(self):
        # Default return is only honored for empty/None inputs, or if validation fails against a list.
        self.assertEqual(standardize_state_name("XYZ"), "XYZ") # Should return original
        self.assertEqual(standardize_state_name("", default_return="EMPTY_STATE"), "EMPTY_STATE")
        valid_list = {"California"}
        self.assertEqual(standardize_state_name("NY", valid_states_list=valid_list, default_return="INVALID_NY"), "INVALID_NY")

    def test_standardize_state_with_comprehensive_default_list(self):
        # Test against the function's own default list of valid states if valid_states_list is None
        self.assertEqual(standardize_state_name("Armed Forces Europe"), "Armed Forces Europe")
        self.assertEqual(standardize_state_name("armed forces pacific", valid_states_list=self.DEFAULT_VALID_STATES_LIST), "Armed Forces Pacific")
        # This should fail if not in the default internal list and no override provided
        self.assertEqual(standardize_state_name("NonExistentArmedForces", valid_states_list=self.DEFAULT_VALID_STATES_LIST, default_return="NOT_FOUND"), "NOT_FOUND")


class TestMapValue(unittest.TestCase):
    mapping = {"apple": "FRUIT", "banana": "FRUIT", "carrot": "VEGETABLE", 123: "NUMBER"}
    default = "UNKNOWN"

    def test_map_value_successful_mapping_case_sensitive(self):
        self.assertEqual(map_value("apple", self.mapping, self.default, case_sensitive=True), "FRUIT")
        self.assertEqual(map_value(123, self.mapping, self.default, case_sensitive=True), "NUMBER")

    def test_map_value_fail_case_sensitive(self):
        self.assertEqual(map_value("Apple", self.mapping, self.default, case_sensitive=True), self.default)

    def test_map_value_successful_mapping_case_insensitive(self):
        self.assertEqual(map_value("Apple", self.mapping, self.default, case_sensitive=False), "FRUIT")
        self.assertEqual(map_value("CARROT", self.mapping, self.default, case_sensitive=False), "VEGETABLE")
        # Numeric keys are typically matched exactly or by string form if not careful
        self.assertEqual(map_value("123", self.mapping, self.default, case_sensitive=False), "NUMBER")


    def test_map_value_not_in_mapping_dict(self):
        self.assertEqual(map_value("grape", self.mapping, self.default), self.default)
        self.assertEqual(map_value(999, self.mapping, self.default), self.default)

    def test_map_value_none_or_empty_input(self):
        self.assertEqual(map_value(None, self.mapping, self.default), self.default)
        self.assertEqual(map_value("", self.mapping, self.default), self.default)
        self.assertEqual(map_value("  ", self.mapping, self.default), self.default)
        self.assertEqual(map_value(None, self.mapping, "SPEC_DEFAULT"), "SPEC_DEFAULT")


class TestStandardizeCountryCode(unittest.TestCase):

    def test_standardize_country_code(self):
        from src.data_cleaning import standardize_country_code
        test_values = {
            "US": "United States", "USA": "United States", "U.S.": "United States",
            "U.S.A.": "United States", "United States": "United States",
            "United States of America": "United States", "us": "United States",
            "usa": "United States", " US ": "United States", "America": "United States",
            "CA": "Canada", "CAN": "Canada", "Canada": "Canada",
            "MX": "Mexico", "MEX": "Mexico", "Mexico": "Mexico",
            "UK": "United Kingdom", "GB": "United Kingdom", "GBR": "United Kingdom",
            "Great Britain": "United Kingdom", "United Kingdom": "United Kingdom",
            "Random": "Random" # Should return as is
        }
        for value, expected in test_values.items():
            with self.subTest(value=value):
                self.assertEqual(standardize_country_code(value), expected)


class TestCleanPercentage(unittest.TestCase):
    def test_clean_percentage_valid_strings(self):
        self.assertEqual(clean_percentage("50"), "50")
        self.assertEqual(clean_percentage("50%"), "50")
        self.assertEqual(clean_percentage("0.5"), "0.5")
        self.assertEqual(clean_percentage(" 0.5% "), "0.5")
        self.assertEqual(clean_percentage("100"), "100")
        self.assertEqual(clean_percentage("100%"), "100")

    def test_clean_percentage_valid_numbers(self):
        self.assertEqual(clean_percentage(50), "50")
        self.assertEqual(clean_percentage(0.5), "0.5")
        self.assertEqual(clean_percentage(100), "100")
        self.assertEqual(clean_percentage(100.0), "100")
        self.assertEqual(clean_percentage(0), "0")

    def test_clean_percentage_empty_and_none(self):
        self.assertEqual(clean_percentage(""), "0")
        self.assertEqual(clean_percentage(None), "0")
        self.assertEqual(clean_percentage("   "), "0")
        self.assertEqual(clean_percentage("nan"), "0")
        self.assertEqual(clean_percentage("NaN"), "0")

    def test_clean_percentage_out_of_bounds(self):
        self.assertEqual(clean_percentage("-10"), "0")
        self.assertEqual(clean_percentage("-10%"), "0")
        self.assertEqual(clean_percentage("-0.5"), "0")
        self.assertEqual(clean_percentage("150"), "100")
        self.assertEqual(clean_percentage("150%"), "100")
        self.assertEqual(clean_percentage(150), "100")

    def test_clean_percentage_invalid_strings(self):
        self.assertEqual(clean_percentage("abc"), "0")
        self.assertEqual(clean_percentage("50 percent"), "0")
        self.assertEqual(clean_percentage("10.5.5"), "0")

if __name__ == '__main__':
    unittest.main()

class TestCleanNumeric(unittest.TestCase):

    def test_clean_numeric_valid(self):
        from src.data_cleaning import clean_numeric

        self.assertEqual(clean_numeric("1000"), "1000")
        self.assertEqual(clean_numeric("10.5"), "10.5")
        self.assertEqual(clean_numeric("10.0"), "10") # Removes redundant .0
        self.assertEqual(clean_numeric("0"), "0")
        self.assertEqual(clean_numeric(100), "100")
        self.assertEqual(clean_numeric(10.5), "10.5")

    def test_clean_numeric_with_symbols(self):
        from src.data_cleaning import clean_numeric

        self.assertEqual(clean_numeric("1,000"), "1000")
        self.assertEqual(clean_numeric("1,234,567.89"), "1234567.89")
        self.assertEqual(clean_numeric("$10.5"), "10.5")
        self.assertEqual(clean_numeric("$1,000.00"), "1000")
        self.assertEqual(clean_numeric(" $ 1,000.50 "), "1000.5")
        self.assertEqual(clean_numeric("-$500"), "-500")

    def test_clean_numeric_empty_none_nan(self):
        from src.data_cleaning import clean_numeric

        self.assertEqual(clean_numeric(""), "")
        self.assertEqual(clean_numeric(None), "")
        self.assertEqual(clean_numeric("   "), "")
        self.assertEqual(clean_numeric("NaN"), "")
        self.assertEqual(clean_numeric("nan"), "")

    def test_clean_numeric_invalid(self):
        from src.data_cleaning import clean_numeric

        self.assertEqual(clean_numeric("invalid_string"), "")
        self.assertEqual(clean_numeric("1000a"), "")
        self.assertEqual(clean_numeric("abc"), "")

class TestTruncateCounselorNotes(unittest.TestCase):
    def test_truncate_happy_path(self):
        # Shorter than max_length
        self.assertEqual(truncate_counselor_notes("Short note.", max_length=20), "Short note.")

    def test_truncate_exact_length(self):
        # Exactly max_length
        self.assertEqual(truncate_counselor_notes("Exactly twenty char.", max_length=20), "Exactly twenty char.")

    def test_truncate_sentence_boundary(self):
        # Truncates at the last sentence boundary '.', '!', '?', '\n' within the limit
        # "Hello world. This is a longer test." max=20 -> "Hello world."
        notes = "Hello world. This is a longer test."
        self.assertEqual(truncate_counselor_notes(notes, max_length=20), "Hello world.")

        # Test with '!'
        notes_exclaim = "Wow! It is very hot outside today."
        self.assertEqual(truncate_counselor_notes(notes_exclaim, max_length=20), "Wow!")

        # Test with '?'
        notes_question = "What time is it? I need to know."
        self.assertEqual(truncate_counselor_notes(notes_question, max_length=20), "What time is it?")

        # Test with '\n'
        notes_newline = "First line.\nSecond line is longer."
        self.assertEqual(truncate_counselor_notes(notes_newline, max_length=15), "First line.\n")

    def test_truncate_word_boundary(self):
        # No sentence boundary within max_length, fallback to word boundary
        # "This is a very long string without punctuation" max=14
        notes = "This is a very long string without punctuation"
        self.assertEqual(truncate_counselor_notes(notes, max_length=14), "This is a")

    def test_truncate_strict(self):
        # No word or sentence boundary within max_length, fallback to strict max_length
        # "Supercalifragilisticexpialidocious" max=10
        notes = "Supercalifragilisticexpialidocious"
        self.assertEqual(truncate_counselor_notes(notes, max_length=10), "Supercalif")

    def test_clean_whitespace_applied(self):
        # Ensure whitespace is cleaned before max_length logic is evaluated
        notes = "   This   has   extra   spaces.   "
        # "This has extra spaces." -> length 22
        self.assertEqual(truncate_counselor_notes(notes, max_length=50), "This has extra spaces.")

    def test_edge_cases(self):
        # Empty string
        self.assertEqual(truncate_counselor_notes("", max_length=20), "")
        # None
        self.assertEqual(truncate_counselor_notes(None, max_length=20), "")
        # Only whitespace
        self.assertEqual(truncate_counselor_notes("   \n  \t  ", max_length=20), "")

if __name__ == '__main__':
    unittest.main()
