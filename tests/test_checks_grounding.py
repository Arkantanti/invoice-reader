import pytest
from decimal import Decimal
from validation.checks import is_grounded, is_amount_grounded


@pytest.mark.parametrize("extracted,raw_text,expected", [
    ("DE89370400440532013000", "IBAN: DE89370400440532013000", True),
    ("DE89370400440532013000", "IBAN: DE89 3704 0044 0532 0130 00", True),  # spaced in source
    ("DE89370400440532013000", "IBAN: DE89370400440532013001", False),      # different value
    ("ACME Trading Co.", "Vendor: ACME Trading Co., Shanghai", True),
    ("ACME Trading Co.", "Vendor: some other company entirely", False),
    ("", "IBAN: DE89370400440532013000", False),   # empty extracted value
    ("DE89370400440532013000", "", False),          # empty raw text
    ("DE89370400440532013000", None, False),        # missing raw text
    (None, "IBAN: DE89370400440532013000", False),  # missing extracted value
])

def test_is_grounded(extracted, raw_text, expected):
    assert is_grounded(extracted, raw_text) is expected

@pytest.mark.parametrize("amount,raw_text,expected", [
    # Exact match, no separators
    (Decimal("1234.50"), "Total: 1234.50 USD", True),
    # Thousands separator (comma)
    (Decimal("1234.50"), "Total: 1,234.50 USD", True),
    # Thousands separator (space)
    (Decimal("1234.50"), "Total: 1 234.50 USD", True),
    # EU-style separators (period thousands, comma decimal)
    (Decimal("1234.50"), "Total: 1.234,50 EUR", True),
    # Precision padding: extracted has 1 decimal, source has 2
    (Decimal("1234.5"), "Total: 1,234.50 USD", True),
    # Amount simply not present
    (Decimal("999.99"), "Total: 1,234.50 USD", False),
    # Decimal-shift error: extracted value is off by a factor of 10
    (Decimal("123.45"), "Total: 1,234.50 USD", False),
    # Truncated substring of a larger number should not match
    (Decimal("234.50"), "Total: 1234.50 USD", False),
    # Amount is a prefix of a longer number in the source
    (Decimal("123.45"), "Total: 123.456 USD", False),
    # Whole-number amount (no meaningful fractional part)
    (Decimal("500.00"), "Total: 500.00 USD", True),
    # Missing raw text
    (Decimal("1234.50"), None, False),
    (Decimal("1234.50"), "", False),
])
def test_is_amount_grounded(amount, raw_text, expected):
    assert is_amount_grounded(amount, raw_text) is expected