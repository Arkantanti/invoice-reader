"""Tests for in-place field editing (``ui.editing``).

Fully offline: builds ``InvoiceData`` + a raw-text string by hand and exercises
the *real* ``validate_invoice`` — no display, no LLM, no tokens. The focus is
that validation (grounding especially) is re-run after every edit/revert.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from models import InvoiceData
from ui import editing
from ui.processing import InvoiceResult
from validation import validate_invoice

# Raw PDF text that grounds every field of the default invoice below. Grounding
# is whitespace/punctuation-insensitive, so exact layout doesn't matter.
RAW_TEXT = (
    "ACME Trading Co.\n"
    "123 Main St\n"
    "Invoice INV-2026-001\n"
    "Date 2026-06-01  Due 2026-06-30\n"
    "Total 1234.50 USD\n"
    "IBAN DE89370400440532013000\n"
    "SWIFT DEUTDEFF\n"
    "Tax 91310000MA1FL5PT7X\n"
)


def make_data(**overrides) -> InvoiceData:
    """A fully valid invoice whose fields are all present in ``RAW_TEXT``."""
    defaults = dict(
        company_name="ACME Trading Co.",
        company_address="123 Main St",
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


def make_result(data: InvoiceData | None = None, raw_text: str = RAW_TEXT) -> InvoiceResult:
    data = data or make_data()
    validated = validate_invoice(data, raw_text)
    return InvoiceResult(path=Path("x.pdf"), validated=validated, raw_text=raw_text, extracted=data)


def _fields(result: InvoiceResult) -> set[str]:
    return {i.field for i in result.validated.issues}


# --------------------------------------------------------------- grounding re-runs

def test_baseline_is_clean():
    result = make_result()
    assert result.validated.issues == []
    assert result.validated.flagged_for_review is False


def test_edit_to_ungrounded_value_adds_error(monkeypatch):
    result = make_result()

    updated = editing.apply_field_edit(result, "invoice_number", "INV-9999-XYZ")

    grounding = [i for i in updated.validated.issues if i.field == "invoice_number"]
    assert len(grounding) == 1
    assert grounding[0].severity == "error"
    assert updated.validated.flagged_for_review is True


def test_edit_to_grounded_value_clears_error():
    # Start with an invoice number that isn't in the PDF text -> grounding fails.
    result = make_result(make_data(invoice_number="WRONG-123"))
    assert "invoice_number" in _fields(result)

    updated = editing.apply_field_edit(result, "invoice_number", "INV-2026-001")

    assert "invoice_number" not in _fields(updated)
    assert updated.validated.flagged_for_review is False


def test_original_result_is_not_mutated_by_edit():
    result = make_result()
    original_validated = result.validated

    editing.apply_field_edit(result, "invoice_number", "INV-9999-XYZ")

    assert result.validated is original_validated
    assert result.validated.issues == []


# ---------------------------------------------------------------- type coercion

def test_amount_is_coerced_to_decimal():
    updated = editing.apply_field_edit(make_result(), "amount", "999.99")
    assert updated.validated.data.amount == Decimal("999.99")


def test_issue_date_is_coerced_to_date():
    updated = editing.apply_field_edit(make_result(), "issue_date", "2026-05-05")
    assert updated.validated.data.issue_date == date(2026, 5, 5)


def test_payment_terms_days_is_coerced_to_int():
    updated = editing.apply_field_edit(make_result(), "payment_terms_days", "10")
    assert updated.validated.data.payment_terms_days == 10


def test_blank_nullable_field_becomes_none():
    updated = editing.apply_field_edit(make_result(), "currency", "")
    assert updated.validated.data.currency is None
    # currency check now runs against None and flags it as a warning.
    currency_issues = [i for i in updated.validated.issues if i.field == "currency"]
    assert len(currency_issues) == 1
    assert currency_issues[0].severity == "warning"


# ------------------------------------------------------------ invalid input rejected

def test_invalid_date_raises_and_leaves_result_untouched():
    result = make_result()
    original_validated = result.validated

    with pytest.raises(ValidationError):
        editing.apply_field_edit(result, "issue_date", "not-a-date")

    assert result.validated is original_validated


def test_clearing_last_payment_field_raises():
    # Only payment_terms_days is set; clearing it violates the model rule that at
    # least one of payment_date / payment_terms_days must be present.
    result = make_result(make_data(payment_date=None, payment_terms_days=14))

    with pytest.raises(ValidationError):
        editing.apply_field_edit(result, "payment_terms_days", "")


# ------------------------------------------------------------------------- revert

def test_revert_restores_extracted_value_and_revalidates():
    result = make_result()
    edited = editing.apply_field_edit(result, "invoice_number", "INV-9999-XYZ")
    assert edited.validated.flagged_for_review is True

    reverted = editing.revert_field(edited, "invoice_number")

    assert reverted.validated.data.invoice_number == "INV-2026-001"
    assert "invoice_number" not in _fields(reverted)
    assert reverted.validated.flagged_for_review is False


def test_field_is_edited_tracks_edit_and_revert():
    result = make_result()
    assert editing.field_is_edited(result, "invoice_number") is False

    edited = editing.apply_field_edit(result, "invoice_number", "INV-9999-XYZ")
    assert editing.field_is_edited(edited, "invoice_number") is True

    reverted = editing.revert_field(edited, "invoice_number")
    assert editing.field_is_edited(reverted, "invoice_number") is False
