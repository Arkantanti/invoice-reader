import pytest
from datetime import date
from decimal import Decimal

from models import InvoiceData
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
        swift_bic="DEUTDEFF",
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
    monkeypatch.setattr(validate, "is_valid_swift", lambda swift: True)
    monkeypatch.setattr(validate, "is_valid_currency_code", lambda currency: True)
    monkeypatch.setattr(validate, "is_issue_date_plausible", lambda issue_date, ref=None: True)
    monkeypatch.setattr(validate, "is_payment_date_after_issue_date", lambda issue_date, payment_date: True)
    monkeypatch.setattr(validate, "is_payment_date_consistent", lambda issue_date, payment_date, terms: True)


def test_all_checks_pass_no_issues(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant, all checks mocked")

    assert result.issues == []
    assert result.flagged_for_review is False


@pytest.mark.parametrize("field_name", ["invoice_number", "iban", "tax_id"])
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
    assert result.flagged_for_review is True


def test_company_name_grounding_failure_is_warning_only(monkeypatch):
    # Company names often don't appear verbatim (formatting/abbreviation), so a
    # grounding miss on company_name is a warning and does not flag for review.
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(
        validate, "is_grounded",
        lambda value, text: False if value == invoice.company_name else True,
    )
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant")

    matching = [i for i in result.issues if i.field == "company_name"]
    assert len(matching) == 1
    assert matching[0].severity == "warning"
    assert result.flagged_for_review is False


def test_amount_grounding_failure_adds_error_issue(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_amount_grounded", lambda value, text: False)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant")

    matching = [i for i in result.issues if i.field == "amount"]
    assert len(matching) == 1
    assert matching[0].severity == "error"
    assert result.flagged_for_review is True

@pytest.mark.parametrize("raw_text", ["", "   \n\t "])
def test_scanned_image_pdf_warns_and_skips_grounding(monkeypatch, raw_text):
    patch_all_checks_pass(monkeypatch)
    # Grounding *would* fail here — assert it is skipped entirely, not run.
    monkeypatch.setattr(validate, "is_grounded", lambda value, text: False)
    monkeypatch.setattr(validate, "is_amount_grounded", lambda value, text: False)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text=raw_text)

    doc_issues = [i for i in result.issues if i.field == "document"]
    assert len(doc_issues) == 1
    assert doc_issues[0].severity == "warning"

    grounding_fields = {"company_name", "invoice_number", "iban", "swift_bic", "tax_id", "amount"}
    assert not any(i.field in grounding_fields for i in result.issues)
    assert result.flagged_for_review is False


def test_text_present_still_runs_grounding(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_amount_grounded", lambda value, text: False)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="a real text layer with content")

    assert any(i.field == "amount" for i in result.issues)          # grounding ran
    assert not any(i.field == "document" for i in result.issues)    # no scanned warning


def test_invalid_currency_adds_warning_only_and_does_not_flag_review(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_valid_currency_code", lambda currency: False)
    invoice = make_invoice(currency="XYZ")

    result = validate_invoice(invoice, raw_text="irrelevant")

    currency_issues = [i for i in result.issues if i.field == "currency"]
    assert len(currency_issues) == 1
    assert currency_issues[0].severity == "warning"
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
    monkeypatch.setattr(validate, "is_valid_swift", lambda swift: False)
    monkeypatch.setattr(validate, "is_valid_currency_code", lambda currency: False)
    monkeypatch.setattr(validate, "is_issue_date_plausible", lambda issue_date, ref=None: False)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant")

    fields_with_issues = {i.field for i in result.issues}
    assert fields_with_issues == {"swift_bic", "currency", "issue_date"}
    assert result.flagged_for_review is True


def test_data_field_preserves_original_invoice(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    invoice = make_invoice()

    result = validate_invoice(invoice, raw_text="irrelevant")

    assert result.data is invoice

def test_malformed_swift_adds_warning_when_iban_valid(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_valid_iban", lambda iban: True)
    monkeypatch.setattr(validate, "is_valid_swift", lambda swift: False)
    invoice = make_invoice(swift_bic="BADSWIFT1")

    result = validate_invoice(invoice, raw_text="irrelevant")

    swift_issues = [i for i in result.issues if i.field == "swift_bic"]
    assert len(swift_issues) == 1
    assert swift_issues[0].severity == "warning"
    assert result.flagged_for_review is False


def test_missing_swift_ok_when_iban_valid(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_valid_iban", lambda iban: True)
    invoice = make_invoice(swift_bic=None)

    result = validate_invoice(invoice, raw_text="irrelevant")

    assert not any(i.field == "swift_bic" for i in result.issues)
    assert result.flagged_for_review is False


def test_missing_swift_adds_error_when_iban_invalid(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_valid_iban", lambda iban: False)
    invoice = make_invoice(swift_bic=None)

    result = validate_invoice(invoice, raw_text="irrelevant")

    swift_issues = [i for i in result.issues if i.field == "swift_bic"]
    assert len(swift_issues) == 1
    assert swift_issues[0].severity == "error"
    assert "required" in swift_issues[0].message
    assert result.flagged_for_review is True


def test_malformed_swift_adds_error_when_iban_invalid(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_valid_iban", lambda iban: False)
    monkeypatch.setattr(validate, "is_valid_swift", lambda swift: False)
    invoice = make_invoice(swift_bic="BADSWIFT1")

    result = validate_invoice(invoice, raw_text="irrelevant")

    swift_issues = [i for i in result.issues if i.field == "swift_bic"]
    assert len(swift_issues) == 1
    assert swift_issues[0].severity == "error"
    assert result.flagged_for_review is True


def test_valid_swift_with_invalid_iban_adds_no_swift_issue(monkeypatch):
    patch_all_checks_pass(monkeypatch)
    monkeypatch.setattr(validate, "is_valid_iban", lambda iban: False)
    monkeypatch.setattr(validate, "is_valid_swift", lambda swift: True)
    invoice = make_invoice(swift_bic="DEUTDEFF")

    result = validate_invoice(invoice, raw_text="irrelevant")

    assert not any(i.field == "swift_bic" for i in result.issues)