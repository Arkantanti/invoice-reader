import pytest
from datetime import date
from validation.checks import is_payment_date_consistent


@pytest.mark.parametrize("issue_date,payment_date,payment_terms_days,expected", [
    (date(2026, 1, 1), date(2026, 1, 31), 30, True),   # consistent
    (date(2026, 1, 1), date(2026, 2, 1), 30, False),   # off by one day
    (date(2026, 1, 1), None, 30, True),                 # only terms set, nothing to check
    (date(2026, 1, 1), date(2026, 1, 31), None, True),  # only date set, nothing to check
    (date(2026, 1, 1), None, None, True),               # neither set — not this function's concern
])
def test_is_payment_date_consistent(issue_date, payment_date, payment_terms_days, expected):
    assert is_payment_date_consistent(issue_date, payment_date, payment_terms_days) is expected