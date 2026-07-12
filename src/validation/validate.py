from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from models import ExtractedInvoice, ValidationIssue, ValidatedInvoice
from validation.checks import (
    is_valid_iban,
    is_known_iban_country,
    is_iban_like,
    is_grounded,
    is_amount_grounded,
    has_text_layer,
    is_valid_currency_code,
    is_issue_date_plausible,
    is_payment_date_after_issue_date,
    is_payment_date_consistent,
)

# Missing-field severity policy. A field the LLM couldn't read comes through as
# None; whether that flags the invoice for review depends on how load-bearing the
# field is for actually paying the invoice.
REQUIRED_ERROR_FIELDS = ("invoice_number", "issue_date", "amount", "account", "tax_id")
REQUIRED_WARNING_FIELDS = ("company_name", "company_address", "currency")

# Fields grounded verbatim against the PDF text (amount is grounded separately,
# from its parsed value). company_name is a soft grounding miss (see below).
_GROUNDED_STRING_FIELDS = ("company_name", "invoice_number", "account", "tax_id")


def _parse_date(raw: Optional[str], field: str, issues: list[ValidationIssue]) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError):
        issues.append(ValidationIssue(
            field=field, message=f"{field} '{raw}' is not a valid ISO date (YYYY-MM-DD)", severity="error",
        ))
        return None


def _parse_decimal(raw: Optional[str], field: str, issues: list[ValidationIssue]) -> Optional[Decimal]:
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        issues.append(ValidationIssue(
            field=field, message=f"{field} '{raw}' is not a valid number", severity="error",
        ))
        return None


def _parse_int(raw: Optional[str], field: str, issues: list[ValidationIssue]) -> Optional[int]:
    if not raw:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        issues.append(ValidationIssue(
            field=field, message=f"{field} '{raw}' is not a whole number of days", severity="error",
        ))
        return None


def validate_invoice(
    invoice: ExtractedInvoice,
    raw_text: str,
    reference_date=None,
) -> ValidatedInvoice:
    issues: list[ValidationIssue] = []

    # --- Parse typed fields from their captured strings ---
    # An unparseable (but present) value is reported here and treated as absent
    # for the checks below, so one bad value can't cascade into misleading
    # errors elsewhere.
    issue_date = _parse_date(invoice.issue_date, "issue_date", issues)
    payment_date = _parse_date(invoice.payment_date, "payment_date", issues)
    amount = _parse_decimal(invoice.amount, "amount", issues)
    payment_terms_days = _parse_int(invoice.payment_terms_days, "payment_terms_days", issues)

    # --- Presence checks ---
    # These enforce "the LLM must have read this" — previously done by non-Optional
    # model fields that threw. A value that was present but failed to parse above
    # already has an error, so don't also report it as missing.
    for field in REQUIRED_ERROR_FIELDS:
        if not getattr(invoice, field):
            issues.append(ValidationIssue(field=field, message=f"{field} is missing", severity="error"))
    for field in REQUIRED_WARNING_FIELDS:
        if not getattr(invoice, field):
            issues.append(ValidationIssue(field=field, message=f"{field} is missing", severity="warning"))

    if not invoice.payment_date and not invoice.payment_terms_days:
        issues.append(ValidationIssue(
            field="payment_date",
            message="Either payment_date or payment_terms_days must be set",
            severity="error",
        ))

    # --- Grounding checks: every present string/amount field ---
    # Scanned / image-only PDFs have no extractable text layer, so grounding
    # can't be performed (it would report every field as "not found"). In that
    # case emit a single warning and skip grounding entirely. The LLM still reads
    # the image, so the format/sanity checks below remain meaningful.
    if not has_text_layer(raw_text):
        issues.append(ValidationIssue(
            field="document",
            message="No extractable text layer — the PDF appears to be a scanned image",
            severity="warning",
        ))
    else:
        grounding_results: dict[str, bool] = {
            field: is_grounded(getattr(invoice, field), raw_text)
            for field in _GROUNDED_STRING_FIELDS
            if getattr(invoice, field)  # only ground values that are present
        }
        if amount is not None:
            grounding_results["amount"] = is_amount_grounded(amount, raw_text)

        for field_name, grounded in grounding_results.items():
            if not grounded:
                issues.append(ValidationIssue(
                    field=field_name,
                    message=f"{field_name} not found verbatim in source PDF text",
                    severity="warning" if field_name == "company_name" else "error",
                ))

    # --- Account check (only when an account was captured) ---
    # The account may be an IBAN or a plain domestic account number. When it's an
    # IBAN we can fully validate it (structure + country + checksum); when it only
    # looks like an IBAN but doesn't validate, that's almost certainly a mistyped
    # IBAN, so flag it. An all-digit domestic account number can't be format-checked
    # (we don't model bank/clearing codes) and is accepted as-is — presence and
    # grounding are its only guards.
    if invoice.account:
        if is_valid_iban(invoice.account):
            if not is_known_iban_country(invoice.account):
                issues.append(ValidationIssue(
                    field="account",
                    message="IBAN country code is not in the known list",
                    severity="warning",
                ))
        elif is_iban_like(invoice.account):
            issues.append(ValidationIssue(
                field="account",
                message=f"'{invoice.account}' looks like an IBAN but is not valid (bad structure or checksum)",
                severity="error",
            ))

    # --- Currency check (only when a currency was captured) ---
    if invoice.currency and not is_valid_currency_code(invoice.currency):
        issues.append(ValidationIssue(
            field="currency",
            message=f"'{invoice.currency}' is not a recognized ISO 4217 currency code",
            severity="warning",
        ))

    # --- Date sanity checks (only when the issue date parsed) ---
    if issue_date is not None:
        if not is_issue_date_plausible(issue_date, reference_date):
            issues.append(ValidationIssue(
                field="issue_date",
                message="Issue date is in the future relative to processing time",
                severity="error",
            ))

        if not is_payment_date_after_issue_date(issue_date, payment_date):
            issues.append(ValidationIssue(
                field="payment_date",
                message="Payment date falls before issue date",
                severity="error",
            ))

        if not is_payment_date_consistent(issue_date, payment_date, payment_terms_days):
            issues.append(ValidationIssue(
                field="payment_date",
                message="payment_date does not match issue_date + payment_terms_days",
                severity="error",
            ))

    # --- Aggregate outcome ---
    flagged_for_review = any(issue.severity == "error" for issue in issues)

    return ValidatedInvoice(
        data=invoice,
        issues=issues,
        flagged_for_review=flagged_for_review,
    )
