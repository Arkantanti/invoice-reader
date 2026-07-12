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

def is_known_iban_country(iban: str) -> bool:
    """
    Check whether an IBAN's country code is present in IBAN_LENGTHS.

    This is independent of checksum/structural validity — an unknown
    country doesn't mean the IBAN is wrong, it means country-specific
    length enforcement couldn't be applied, which is worth surfacing
    separately from a hard validation failure.
    """
    if not iban:
        return False

    country_code = iban.replace(" ", "").upper()[:2]
    return country_code in IBAN_LENGTHS


def is_iban_like(account: str) -> bool:
    """
    Whether a value is *shaped* like an IBAN attempt (two letters, two check
    digits, then alphanumerics) even if the checksum or length is wrong.

    Used to tell a (possibly mistyped) IBAN apart from a plain domestic account
    number: an IBAN-shaped value that fails ``is_valid_iban`` is almost certainly
    a transcription error worth flagging, whereas an all-digit domestic account
    number simply can't be IBAN-validated and is accepted as-is.
    """
    if not account:
        return False
    return bool(IBAN_GENERAL_PATTERN.match(account.replace(" ", "").upper()))

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

    # pdfplumber interleaves numbers with layout noise when extracting them:
    # stray spaces/newlines, a thousands separator *and* a space (e.g.
    # "1 ,140.00"), and — for underlined total fields — leader/fill underscores
    # between the digits (e.g. "Net value ___3_6_.8_0_0_,_40_" for 36.800,40).
    # Treat any run of whitespace / thousands punctuation / underscore as an
    # insignificant separator between the digits and around the decimal mark.
    noise = r"[\s.,_]*"
    int_pattern = noise.join(list(int_part))
    pattern = rf"(?<!\d){int_pattern}[\s_]*[.,][\s_]*{frac_part}(?!\d)"

    return re.search(pattern, raw_text) is not None

def has_text_layer(raw_text: str) -> bool:
    """Whether the PDF yielded any extractable text.

    Scanned / image-only invoices have no text layer, so pdfplumber returns an
    empty (or whitespace-only) string. Grounding checks compare extracted values
    against this text, so when it's absent grounding can't be performed at all —
    the caller should surface that as its own warning rather than reporting every
    field as "not found verbatim".
    """
    return bool(raw_text and raw_text.strip())

from datetime import date, timedelta
from typing import Optional

def is_payment_date_consistent(
    issue_date: date,
    payment_date: Optional[date],
    payment_terms_days: Optional[int],
) -> bool:
    """
    Check whether payment_date matches issue_date + payment_terms_days,
    when both are present. If only one (or neither) is set, there's
    nothing to cross-check, so this returns True — the "at least one
    must be set" rule is enforced upstream at extraction, not here.
    """
    if payment_date is None or payment_terms_days is None:
        return True

    expected_date = issue_date + timedelta(days=payment_terms_days)
    return payment_date == expected_date

ISO_4217_CODES = {
    "AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG", "AZN",
    "BAM", "BBD", "BDT", "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BRL",
    "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHF", "CLP", "CNY",
    "COP", "CRC", "CUP", "CVE", "CZK", "DJF", "DKK", "DOP", "DZD", "EGP",
    "ERN", "ETB", "EUR", "FJD", "FKP", "GBP", "GEL", "GHS", "GIP", "GMD",
    "GNF", "GTQ", "GYD", "HKD", "HNL", "HTG", "HUF", "IDR", "ILS", "INR",
    "IQD", "IRR", "ISK", "JMD", "JOD", "JPY", "KES", "KGS", "KHR", "KMF",
    "KPW", "KRW", "KWD", "KYD", "KZT", "LAK", "LBP", "LKR", "LRD", "LSL",
    "LYD", "MAD", "MDL", "MGA", "MKD", "MMK", "MNT", "MOP", "MRU", "MUR",
    "MVR", "MWK", "MXN", "MYR", "MZN", "NAD", "NGN", "NIO", "NOK", "NPR",
    "NZD", "OMR", "PAB", "PEN", "PGK", "PHP", "PKR", "PLN", "PYG", "QAR",
    "RON", "RSD", "RUB", "RWF", "SAR", "SBD", "SCR", "SDG", "SEK", "SGD",
    "SHP", "SLE", "SOS", "SRD", "SSP", "STN", "SYP", "SZL", "THB", "TJS",
    "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS", "UAH", "UGX", "USD",
    "UYU", "UZS", "VES", "VND", "VUV", "WST", "XAF", "XCD", "XOF", "XPF",
    "YER", "ZAR", "ZMW", "ZWL",
}


def is_valid_currency_code(currency: str) -> bool:
    """
    Check whether a string is a valid, active ISO 4217 currency code.

    Case-sensitive by design: a real invoice's currency code should already
    be uppercase (that's the ISO standard), so an unexpectedly lowercase
    extraction (e.g. "cny" instead of "CNY") is itself worth flagging as
    a formatting anomaly rather than silently normalizing and passing.
    """
    if not currency:
        return False

    return currency in ISO_4217_CODES

from datetime import date
from typing import Optional


def is_issue_date_plausible(issue_date: date, reference_date: Optional[date] = None) -> bool:
    """
    Check that issue_date isn't in the future relative to processing time.

    reference_date defaults to today if not supplied, but accepting it as
    a parameter (rather than calling date.today() internally) keeps this
    function pure and testable — tests can pin a fixed reference_date
    instead of depending on the actual current date.
    """
    if reference_date is None:
        reference_date = date.today()

    return issue_date <= reference_date


def is_payment_date_after_issue_date(issue_date: date, payment_date: Optional[date]) -> bool:
    """
    Check that payment_date, when present, doesn't fall before issue_date.

    Returns True when payment_date is None — nothing to check in that case,
    consistent with is_payment_date_consistent's handling of absent fields.
    """
    if payment_date is None:
        return True

    return payment_date >= issue_date

