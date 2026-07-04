from commons import InvoiceData, ValidationIssue, ValidatedInvoice
from validation.checks import (
    is_valid_iban,
    is_known_iban_country,
    is_grounded,
    is_amount_grounded,
    is_valid_currency_code,
    is_issue_date_plausible,
    is_payment_date_after_issue_date,
    is_payment_date_consistent,
)


def validate_invoice(
    invoice: InvoiceData,
    raw_text: str,
    reference_date=None,
) -> ValidatedInvoice:
    issues: list[ValidationIssue] = []

    # --- Grounding checks: every string/amount field ---
    grounding_results = {
        "company_name": is_grounded(invoice.company_name, raw_text),
        "invoice_number": is_grounded(invoice.invoice_number, raw_text),
        "iban": is_grounded(invoice.iban, raw_text),
        "tax_id": is_grounded(invoice.tax_id, raw_text),
        "amount": is_amount_grounded(invoice.amount, raw_text),
    }

    for field_name, grounded in grounding_results.items():
        if not grounded:
            issues.append(ValidationIssue(
                field=field_name,
                message=f"{field_name} not found verbatim in source PDF text",
                severity="error",
            ))

    # --- IBAN checksum check ---
    if not is_valid_iban(invoice.iban):
        issues.append(ValidationIssue(
            field="iban",
            message="IBAN failed mod-97 checksum validation",
            severity="error",
        ))
    elif not is_known_iban_country(invoice.iban):
        issues.append(ValidationIssue(
            field="iban",
            message="IBAN country code is not in the known-length table; only checksum was verified",
            severity="warning",
        ))

    # --- Currency check ---
    if not is_valid_currency_code(invoice.currency):
        issues.append(ValidationIssue(
            field="currency",
            message=f"'{invoice.currency}' is not a recognized ISO 4217 currency code",
            severity="warning",
        ))

    # --- Date sanity checks ---
    if not is_issue_date_plausible(invoice.issue_date, reference_date):
        issues.append(ValidationIssue(
            field="issue_date",
            message="Issue date is in the future relative to processing time",
            severity="error",
        ))

    if not is_payment_date_after_issue_date(invoice.issue_date, invoice.payment_date):
        issues.append(ValidationIssue(
            field="payment_date",
            message="Payment date falls before issue date",
            severity="error",
        ))

    if not is_payment_date_consistent(invoice.issue_date, invoice.payment_date, invoice.payment_terms_days):
        issues.append(ValidationIssue(
            field="payment_date",
            message="payment_date does not match issue_date + payment_terms_days",
            severity="error",
        ))

    # --- Aggregate outcome ---
    grounding_ok = all(grounding_results.values())
    flagged_for_review = any(issue.severity == "error" for issue in issues) or not grounding_ok

    return ValidatedInvoice(
        data=invoice,
        grounding_ok=grounding_ok,
        issues=issues,
        flagged_for_review=flagged_for_review,
    )