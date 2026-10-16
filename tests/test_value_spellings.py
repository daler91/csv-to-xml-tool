"""Every way an export writes a value must clean to the same filed value.

The same date, amount, phone or answer reaches the converter spelled the ways
Salesforce reports, Excel and people write it, and a spelling the cleaners
did not know was either refused (and the value defaulted or dropped) or --
worse -- read as something else. Many of the last fixes were one such
spelling at a time: day-first dates, a date-time with a comma, "(1,500)",
"0E+5000", "yes" in lower case, and a phone number whose first ten digits
were not the number.

Each class below lists spellings of one value that must all clean to it;
each REFUSED list holds near misses that must clean to "" -- not a guess --
so the converter reports them instead of filing a wrong value.
"""

import pytest

from src.data_cleaning import (
    clean_numeric,
    clean_phone_number,
    format_date,
    is_affirmative,
    is_ambiguous_date,
    is_negative,
    map_gender_to_sex,
    standardize_state_name,
)


def _classes(table):
    return [pytest.param(spelling, value, id=f"{spelling!r}") for value, spellings in table.items()
            for spelling in spellings]


DATES = {
    "2025-01-13": [
        "2025-01-13", "2025-1-13", "2025/01/13",
        "1/13/2025", "01/13/2025", "1-13-2025", "1/13/25", "01-13-25",
        # Day-first, readable because 13 can only be a day.
        "13/01/2025", "13/1/25", "13-01-2025",
        "Jan 13, 2025", "January 13, 2025", "JAN 13, 2025", "jan 13, 2025",
        # Salesforce Date/Time fields, from a report export and from the API.
        "1/13/2025 10:30 AM", "1/13/2025, 10:30 AM", "1/13/2025 10:30:15 PM", "1/13/2025 10:30am",
        "1/13/2025 10:30 a.m.", "Jan 13, 2025 10:30 AM", "Jan 13, 2025, 10:30 AM",
        "2025-01-13T10:30:00", "2025-01-13 09:15:00", "2025-01-13T23:30:00.000Z",
        "2025-01-13T10:30:00+05:30",
        " 1/13/2025 ",
    ],
}
DATES_REFUSED = [
    "02/30/2025", "2025-02-29", "13/13/2025", "32/01/2025", "0/13/2025", "2025-13-01",
    "1/13", "Jan 13", "2025", "not a date", "N/A", "TBD", "#N/A",
]


@pytest.mark.parametrize("spelling, value", _classes(DATES))
def test_a_date_reads_the_same_however_it_is_written(spelling, value):
    assert format_date(spelling) == value


@pytest.mark.parametrize("spelling", DATES_REFUSED)
def test_an_impossible_or_partial_date_is_refused_not_guessed(spelling):
    assert format_date(spelling) == ""


def test_an_ambiguous_date_reads_month_first_and_says_so():
    assert format_date("03/04/2025") == "2025-03-04"
    assert is_ambiguous_date("03/04/2025")
    assert not is_ambiguous_date("1/13/2025")


def test_a_two_digit_year_is_never_in_the_future():
    # strptime reads 68 as 2068; a business started in 1968 is the reading.
    assert format_date("01/05/68") == "1968-01-05"


AMOUNTS = {
    "1500": ["1500", "1,500", "$1,500", "$1,500.00", "$ 1,500", "1500.00", "1500.0", "1,500.00 ",
             " 1500 ", "1 500", "+1500", "1500$", "\u00a01500", "1.5E3", "1.5e+3"],
    "-1500": ["(1,500)", "($1,500.00)", "-1,500", "-$1500", "$-1500", "-1500."],
    "0": ["0", "0.00", "$0", "$0.00", "-0", "(0)", "0E+5000"],
    "12.5": ["12.5", "12.50", "$12.5", "1.25E1"],
}
# Not 1E+400: an amount merely too large for its field is read, so the schema
# guard reports it as over the maximum; only an absurd exponent is no amount.
AMOUNTS_REFUSED = ["abc", "USD 1500", "€1500", "1500-", "\u22121500", "1e5000", "NaN", "Infinity",
                   "12.5.3", "$", "-", "50%"]


@pytest.mark.parametrize("spelling, value", _classes(AMOUNTS))
def test_an_amount_reads_the_same_however_it_is_written(spelling, value):
    assert clean_numeric(spelling) == value


@pytest.mark.parametrize("spelling", AMOUNTS_REFUSED)
def test_something_that_is_not_an_amount_is_refused(spelling):
    assert clean_numeric(spelling) == ""


PHONES = {
    "5155551234": [
        "(515) 555-1234", "(515)555-1234", "515-555-1234", "515.555.1234", "515 555 1234",
        "515/555-1234", "5155551234", " 515-555-1234 ", "Cell: 515-555-1234",
        "+1 515 555 1234", "+1 (515) 555-1234", "1-515-555-1234", "15155551234",
        # What follows the number is cut off where it starts.
        "515-555-1234 ext. 12", "515-555-1234 x12", "1-515-555-1234 ext 12",
        "515-555-1234 / 515-555-9999",
    ],
    "1234567890": ["1234567890 x5", "123-456-7890 ext 123"],
}
PHONES_REFUSED = [
    # Each of these used to be filed as a different, ten-digit number.
    "+44 20 7946 0958", "011 44 20 7946 0958", "25155551234", "515-555-12345",
    "555-1234", "1-800-FLOWERS", "\uff15\uff11\uff15\uff15\uff15\uff15\uff11\uff12\uff13\uff14", "+1", "x",
]


@pytest.mark.parametrize("spelling, value", _classes(PHONES))
def test_a_phone_reads_the_same_however_it_is_written(spelling, value):
    assert clean_phone_number(spelling) == value


@pytest.mark.parametrize("spelling", PHONES_REFUSED)
def test_a_phone_that_is_not_a_us_number_is_refused_not_cut_to_ten_digits(spelling):
    assert clean_phone_number(spelling) == ""


ANSWERS = {
    "Yes": ["Yes", "YES", "yes", "y", "Y", " Yes ", "true", "TRUE", "1"],
    "No": ["No", "NO", "no", "n", "N", " no ", "false", "FALSE", "0"],
    # Neither: the converter files its default and says so.
    "?": ["Yes.", "No.", "Yes - in business", "None", "N/A", "Not yet", "Maybe", ""],
}


@pytest.mark.parametrize("spelling, value", _classes(ANSWERS))
def test_a_yes_no_answer_reads_the_same_in_any_case(spelling, value):
    read = "Yes" if is_affirmative(spelling) else "No" if is_negative(spelling) else "?"
    assert read == value


GENDERS = {
    "Female": ["Female", "FEMALE", "female", " female ", "F", "f", "Woman", "woman", "Transgender Female"],
    "Male": ["Male", "MALE", "male ", "M", "m", "Man", "Trans Male"],
    "": ["Prefer not to say", "Non-binary", "Femme", "Unknown", "", "Préfère ne pas répondre"],
}


@pytest.mark.parametrize("spelling, value", _classes(GENDERS))
def test_a_gender_answer_reads_the_same_however_it_is_written(spelling, value):
    assert map_gender_to_sex(spelling) == value


STATES = {
    "Iowa": ["Iowa", "IOWA", "iowa", "IA", "ia", "Ia", " IA "],
    "District of Columbia": ["District of Columbia", "DC", "D.C."],
    "Puerto Rico": ["Puerto Rico", "PR"],
}


@pytest.mark.parametrize("spelling, value", _classes(STATES))
def test_a_state_reads_the_same_however_it_is_written(spelling, value):
    assert standardize_state_name(spelling) == value
