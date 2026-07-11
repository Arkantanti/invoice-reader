"""In-place editing of extracted invoice fields for the review UI.

Deliberately free of any Tkinter imports (like ``processing``) so it can be
unit-tested without a display. Every field of ``ExtractedInvoice`` is a nullable
string, so an edit is just "set this string (or clear it to None) and re-run the
*pure* ``validate_invoice`` against the retained raw PDF text". Nothing here
raises on a bad value — a malformed amount or date simply becomes a validation
issue, surfaced in the UI like any other. **No extraction / LLM call is ever made
here**, so editing never spends tokens.
"""
from dataclasses import replace

from models import ExtractedInvoice
from validation import validate_invoice

from .processing import InvoiceResult


def _revalidate(result: InvoiceResult, new_data: ExtractedInvoice) -> InvoiceResult:
    """Re-run validation for ``new_data`` and return a fresh ``InvoiceResult``.

    The original ``result`` is left untouched; ``raw_text`` and ``extracted``
    carry over so further edits/reverts keep working.
    """
    validated = validate_invoice(new_data, result.raw_text or "")
    return replace(result, validated=validated)


def apply_field_edit(result: InvoiceResult, field_name: str, text: str) -> InvoiceResult:
    """Apply an edit to one field and re-validate.

    ``text`` is the raw string from the editor; blank (or whitespace-only) clears
    the field to ``None``. Returns a new ``InvoiceResult`` with the updated data
    and freshly computed issues. Never raises on the value itself — validation
    reports anything wrong with it.
    """
    if result.validated is None:
        raise ValueError("cannot edit a result that has no extracted data")
    value = text.strip() or None
    new_data = result.validated.data.model_copy(update={field_name: value})
    return _revalidate(result, new_data)


def revert_field(result: InvoiceResult, field_name: str) -> InvoiceResult:
    """Restore ``field_name`` to its originally extracted value and re-validate."""
    if result.validated is None or result.extracted is None:
        raise ValueError("cannot revert a result without an extraction snapshot")
    original = getattr(result.extracted, field_name)
    new_data = result.validated.data.model_copy(update={field_name: original})
    return _revalidate(result, new_data)


def field_is_edited(result: InvoiceResult, field_name: str) -> bool:
    """Whether ``field_name``'s current value differs from the extracted one."""
    if result.validated is None or result.extracted is None:
        return False
    return getattr(result.validated.data, field_name) != getattr(result.extracted, field_name)
