import pytest
from validation.checks import is_valid_currency_code


@pytest.mark.parametrize("currency,expected", [
    ("USD", True),
    ("CNY", True),
    ("EUR", True),
    ("usd", False),   # case-sensitive by design — lowercase is a formatting anomaly, not normalized
    ("US", False),    # too short, not a prefix match
    ("USDD", False),  # too long, not a partial match
    ("XXX", False),   # ISO-reserved "no currency" code, deliberately excluded — should not appear on a real invoice
    ("", False),      # empty
    (None, False),    # missing
])
def test_is_valid_currency_code(currency, expected):
    assert is_valid_currency_code(currency) is expected