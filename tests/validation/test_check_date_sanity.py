import pytest
from datetime import date
from validation.checks import is_issue_date_plausible, is_payment_date_after_issue_date


@pytest.mark.parametrize("issue_date,reference_date,expected", [
    (date(2026, 6, 1), date(2026, 7, 4), True),   # normal past date
    (date(2026, 7, 4), date(2026, 7, 4), True),   # same day as reference — boundary, valid
    (date(2026, 7, 5), date(2026, 7, 4), False),  # one day in the future
    (date(2027, 1, 1), date(2026, 7, 4), False),  # year misread, far future
])
def test_is_issue_date_plausible(issue_date, reference_date, expected):
    assert is_issue_date_plausible(issue_date, reference_date) is expected


@pytest.mark.parametrize("issue_date,payment_date,expected", [
    (date(2026, 6, 1), date(2026, 6, 30), True),   # normal, payment after issue
    (date(2026, 6, 1), date(2026, 6, 1), True),    # same day — boundary, valid
    (date(2026, 6, 1), date(2026, 5, 15), False),  # payment before issue — impossible
    (date(2026, 6, 1), None, True),                 # no payment_date — nothing to check
])
def test_is_payment_date_after_issue_date(issue_date, payment_date, expected):
    assert is_payment_date_after_issue_date(issue_date, payment_date) is expected