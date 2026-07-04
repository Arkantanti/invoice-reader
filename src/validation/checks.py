import re

# ISO 13616 fixed IBAN lengths by country code.
# Source: SWIFT IBAN Registry. Only includes countries realistically
# relevant to wire-transfer vendor payments (EU + common trading partners).
# Extend this table as new vendor countries appear.
IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28,
    "BA": 20, "BE": 16, "BG": 22, "BH": 22, "BR": 29,
    "CH": 21, "CR": 22, "CY": 28, "CZ": 24,
    "DE": 22, "DK": 18, "DO": 28,
    "EE": 20, "EG": 29, "ES": 24,
    "FI": 18, "FO": 18, "FR": 27,
    "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28,
    "HR": 21, "HU": 28,
    "IE": 22, "IL": 23, "IQ": 23, "IS": 26, "IT": 27,
    "JO": 30,
    "KW": 30, "KZ": 20,
    "LB": 28, "LC": 32, "LI": 21, "LT": 20, "LU": 20, "LV": 21,
    "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MR": 27, "MT": 31, "MU": 30,
    "NL": 18, "NO": 15,
    "PK": 24, "PL": 28, "PS": 29, "PT": 25,
    "QA": 29,
    "RO": 24, "RS": 22,
    "SA": 24, "SC": 31, "SE": 24, "SI": 19, "SK": 24, "SM": 27,
    "TL": 23, "TN": 24, "TR": 26,
    "UA": 29,
    "VA": 22, "VG": 24,
    "XK": 20,
}

IBAN_GENERAL_PATTERN = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")


def is_valid_iban(iban: str) -> bool:
    """
    Validate an IBAN using structural checks (general format + country-specific
    length) followed by the ISO 7064 MOD97-10 checksum.

    Returns False for:
    - empty/missing input
    - wrong general shape (2 letters + 2 digits + 11-30 alphanumeric)
    - wrong length for the claimed country (if country is in IBAN_LENGTHS)
    - failed mod-97 checksum
    """
    if not iban:
        return False

    cleaned = iban.replace(" ", "").upper()

    if not IBAN_GENERAL_PATTERN.match(cleaned):
        return False

    country_code = cleaned[:2]
    expected_length = IBAN_LENGTHS.get(country_code)
    if expected_length is not None and len(cleaned) != expected_length:
        return False

    rearranged = cleaned[4:] + cleaned[:4]
    numeric_str = "".join(
        str(ord(ch) - ord("A") + 10) if ch.isalpha() else ch
        for ch in rearranged
    )

    return int(numeric_str) % 97 == 1

from decimal import Decimal

def _normalize_for_grounding(text: str) -> str:
    """
    Strip whitespace and punctuation commonly inserted/removed by OCR,
    formatting, or the LLM's own normalization, so grounding compares
    on substance rather than incidental formatting.
    """
    return re.sub(r"[\s,.\-/]", "", text).upper()


def is_grounded(extracted_value: str, raw_text: str) -> bool:
    """
    Check whether an extracted string value appears in the raw PDF text,
    tolerant of whitespace/punctuation differences (e.g. IBAN with spaces,
    amounts with thousands separators, dates in different formats).

    Returns False for empty/missing extracted_value or raw_text, since an
    empty value can't be meaningfully "grounded."
    """
    if not extracted_value or not raw_text:
        return False

    normalized_value = _normalize_for_grounding(extracted_value)
    normalized_text = _normalize_for_grounding(raw_text)

    return normalized_value in normalized_text

def is_amount_grounded(extracted_amount: Decimal, raw_text: str) -> bool:
    if raw_text is None:
        return False

    quantized = extracted_amount.quantize(Decimal("0.01"))
    sign, digits, exponent = quantized.as_tuple()
    digit_str = "".join(str(d) for d in digits)

    frac_len = -exponent
    int_part = digit_str[:-frac_len] if frac_len else digit_str
    frac_part = digit_str[-frac_len:] if frac_len else ""
    int_part = int_part or "0"

    int_pattern = r"[.,\s]?".join(list(int_part))
    pattern = rf"(?<!\d){int_pattern}[.,]{frac_part}(?!\d)"

    return re.search(pattern, raw_text) is not None