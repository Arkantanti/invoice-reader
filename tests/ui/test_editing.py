"""Tests for in-place field editing (``ui.editing``).

Fully offline: builds an ``ExtractedInvoice`` (all string fields) + a raw-text
string by hand and exercises the *real* ``validate_invoice`` — no display, no
LLM, no tokens. The focus is that validation (grounding especially) is re-run
after every edit/revert, and that a bad value becomes an issue rather than an
exception.
"""
from pathlib import Path

from models import ExtractedInvoice
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


def make_data(**overrides) -> ExtractedInvoice:
    """A fully valid invoice whose fields are all present in ``RAW_TEXT``."""
    defaults = dict(
        company_name="ACME Trading Co.",
        company_address="123 Main St",
        invoice_number="INV-2026-001",
        issue_date="2026-06-01",
        payment_date="2026-06-30",
        payment_terms_days="29",
        amount="1234.50",
        currency="USD",
        iban="DE89370400440532013000",
        swift_bic="DEUTDEFF",
        tax_id="91310000MA1FL5PT7X",
    )
    defaults.update(overrides)
    return ExtractedInvoice(**defaults)


def make_result(data: ExtractedInvoice | None = None, raw_text: str = RAW_TEXT) -> InvoiceResult:
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


def test_edit_to_ungrounded_value_adds_error():
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


# ------------------------------------------------------- edits store raw strings

def test_edit_stores_raw_string():
    updated = editing.apply_field_edit(make_result(), "amount", "999.99")
    assert updated.validated.data.amount == "999.99"


def test_edit_strips_and_blanks_to_none():
    updated = editing.apply_field_edit(make_result(), "currency", "   ")
    assert updated.validated.data.currency is None
    # currency is now missing -> a warning (not an error).
    currency_issues = [i for i in updated.validated.issues if i.field == "currency"]
    assert len(currency_issues) == 1
    assert currency_issues[0].severity == "warning"


# ------------------------------------------ bad values become issues, not raises

def test_invalid_amount_edit_adds_error_not_exception():
    updated = editing.apply_field_edit(make_result(), "amount", "abc")

    amount_issues = [i for i in updated.validated.issues if i.field == "amount"]
    assert any("not a valid number" in i.message for i in amount_issues)
    assert updated.validated.flagged_for_review is True


def test_invalid_date_edit_adds_error_not_exception():
    updated = editing.apply_field_edit(make_result(), "issue_date", "not-a-date")

    date_issues = [i for i in updated.validated.issues if i.field == "issue_date"]
    assert any("not a valid ISO date" in i.message for i in date_issues)


def test_clearing_last_payment_field_adds_error_not_exception():
    result = make_result(make_data(payment_date=None, payment_terms_days="14"))

    updated = editing.apply_field_edit(result, "payment_terms_days", "")

    assert any("Either payment_date" in i.message for i in updated.validated.issues)


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
