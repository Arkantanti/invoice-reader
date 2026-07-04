import pytest
from validation.checks import is_valid_iban


@pytest.mark.parametrize("iban,expected", [
    ("DE89370400440532013000", True),
    ("DE89 3704 0044 0532 0130 00", True),   # spaces, as typed on invoices
    ("de89370400440532013000", True),        # lowercase
    ("DE89370400440532013001", False),       # bad checksum
    ("", False),                             # empty
    ("89370400440532013001", False),         # no country/check-digit prefix
    ("XX361234567890", False),               # too short
    ("XX900000000000000000000000000000000", False),  # too long
    ("DE89-3704-0044-0532-0130-00", False),  # invalid characters
    ("DE8937040044053201300", False),        # right prefix, wrong length for DE
])
def test_is_valid_iban(iban, expected):
    assert is_valid_iban(iban) is expected


def test_unlisted_country_falls_back_to_general_check():
    # Country not in IBAN_LENGTHS — should not hard-fail on length alone
    assert is_valid_iban("SV92CENR00000000123456789012") is True

from validation.checks import is_known_iban_country

@pytest.mark.parametrize("iban,expected", [
    ("DE89370400440532013000", True),            # known country (Germany)
    ("PL61109010140000071219812874", True),       # known country (Poland)
    ("SV92CENR00000000123456789012", False),      # unknown country (El Salvador, not in table)
    ("XX90000000000000000000000000", False),      # fabricated/unlisted country code
    ("de89370400440532013000", True),             # lowercase input
    ("", False),                                   # empty
    (None, False),                                 # missing
])
def test_is_known_iban_country(iban, expected):
    assert is_known_iban_country(iban) is expected