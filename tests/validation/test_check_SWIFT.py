import pytest
from validation.checks import is_valid_swift


@pytest.mark.parametrize("swift_bic", [
    "DEUTDEFF",       # 8-char, valid
    "DEUTDEFF500",    # 11-char, valid with branch code
    "ICBKCNBJ",       # 8-char, Chinese bank
    "ICBKCNBJ123",    # 11-char with branch
])
def test_valid_swift_formats(swift_bic):
    assert is_valid_swift(swift_bic) is True


@pytest.mark.parametrize("swift_bic", [
    "DEUTDEFF5",      # 9 chars — invalid length
    "deutdeff",       # lowercase
    "DEUT12FF",       # digits in bank code (must be letters)
    "DEUTD11F",       # digit in country code (must be letters)
    "",               # empty
    "DEUTDEFF12",     # 10 chars — invalid length
])
def test_invalid_swift_formats(swift_bic):
    assert is_valid_swift(swift_bic) is False