import pytest
from datetime import date
from decimal import Decimal

from commons import InvoiceData
from validation import validate
from validation.validate import validate_invoice


def make_invoice(**overrides):
    """Helper: a fully valid invoice, override specific fields per test."""
    defaults = dict(
        company_name="ACME Trading Co.",
        company_address="123 Main St, Shanghai, China",
        invoice_number="INV-2026-001",
        issue_date=date(2026, 6, 1),
        payment_date=date(2026, 6, 30),
        payment_terms_days=29,
        amount=Decimal("1234.50"),
        currency="USD",
        iban="DE89370400440532013000",
        tax_id="91310000MA1FL5PT7X",
    )
    defaults.update(overrides)
    return InvoiceData(**defaults)


def patch_all_checks_pass(monkeypatch):
    """Patch every check function to return True, as a clean baseline."""
    monkeypatch.setattr(validate, "is_grounded", lambda value, text: True)
    monkeypatch.setattr(validate, "is_amount_grounded", lambda value, text: True)
    monkeypatch.setattr(validate, "is_valid_iban", lambda iban: True)
    monkeypatch.setattr(validate, "is_known_iban_country", lambda iban: True)
    monkeypatch.setattr(validate, "is_valid_currency_code", lambda currency: True)
    monkeypatch.setattr(validate, "is_issue_date_plausible", lambda issue_date, ref=None: True)
    monkeypatch.setattr(validate, "is_payment_date_after_issue_date", lambda issue_date, payment_date: True)
    monkeypatch.setattr(validate, "is_payment_date_consistent", lambda issue_date, payment_date, terms: True)


def test_all_checks_pass_no_issues(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant, all checks mocked")

    assert result.issues == []
    assert result.grounding_ok is True
    assert result.flagged_for_review is False


@pytest.mark.parametrize("field_name", ["company_name", "invoice_number", "iban", "tax_id"])
def test_string_field_grounding_failure_adds_error_issue(monkeypatch, field_name):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(
        validate, "is_grounded",
        lambda value, text: False if value == getattr(invoice, field_name) else True,
    )
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant")

    matching = [i for i in result.issues if i.field == field_name]
    assert len(matching) == 1
    assert matching[0].severity == "error"
    assert result.grounding_ok is False
    assert result.flagged_for_review is True


def test_amount_grounding_failure_adds_error_issue(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_amount_grounded", lambda value, text: False)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant")

    matching = [i for i in result.issues if i.field == "amount"]
    assert len(matching) == 1
    assert matching[0].severity == "error"
    assert result.grounding_ok is False
    assert result.flagged_for_review is True


def test_iban_checksum_failure_adds_error_and_skips_country_check(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_valid_iban", lambda iban: False)
    # Deliberately also fail the country check to prove the elif skips it
    monkeypatch.setattr(validate, "is_known_iban_country", lambda iban: False)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant")

    iban_issues = [i for i in result.issues if i.field == "iban"]
    assert len(iban_issues) == 1  # only the checksum error, not also a country warning
    assert iban_issues[0].severity == "error"
    assert "checksum" in iban_issues[0].message
    assert result.flagged_for_review is True


def test_unknown_iban_country_adds_warning_when_checksum_valid(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_valid_iban", lambda iban: True)
    monkeypatch.setattr(validate, "is_known_iban_country", lambda iban: False)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant")

    iban_issues = [i for i in result.issues if i.field == "iban"]
    assert len(iban_issues) == 1
    assert iban_issues[0].severity == "warning"
    assert "known-length table" in iban_issues[0].message


def test_invalid_currency_adds_warning_only_and_does_not_flag_review(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_valid_currency_code", lambda currency: False)
    invoice = make_invoice(currency="XYZ")

    result = validate_invoice(invoice, raw_text="irrelevant")

    currency_issues = [i for i in result.issues if i.field == "currency"]
    assert len(currency_issues) == 1
    assert currency_issues[0].severity == "warning"
    # A single warning-only issue, with grounding otherwise clean, should not flag for review
    assert result.flagged_for_review is False


def test_issue_date_in_future_adds_error_issue(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_issue_date_plausible", lambda issue_date, ref=None: False)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant")

    matching = [i for i in result.issues if i.field == "issue_date"]
    assert len(matching) == 1
    assert matching[0].severity == "error"
    assert result.flagged_for_review is True


def test_payment_before_issue_date_adds_error_issue(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_payment_date_after_issue_date", lambda issue_date, payment_date: False)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant")

    matching = [i for i in result.issues if i.field == "payment_date"]
    assert any(i.severity == "error" for i in matching)
    assert result.flagged_for_review is True


def test_payment_date_inconsistent_with_terms_adds_error_issue(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_payment_date_consistent", lambda issue_date, payment_date, terms: False)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant")

    matching = [i for i in result.issues if i.field == "payment_date"]
    assert any(i.severity == "error" for i in matching)
    assert result.flagged_for_review is True


def test_multiple_failures_all_accumulate(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_valid_iban", lambda iban: False)
    monkeypatch.setattr(validate, "is_valid_currency_code", lambda currency: False)
    monkeypatch.setattr(validate, "is_issue_date_plausible", lambda issue_date, ref=None: False)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant")

    fields_with_issues = {i.field for i in result.issues}
    assert fields_with_issues == {"iban", "currency", "issue_date"}
    assert result.flagged_for_review is True


def test_data_field_preserves_original_invoice(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant")

    assert result.data is invoice