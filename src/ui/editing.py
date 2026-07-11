"""In-place editing of extracted invoice fields for the review UI.

Deliberately free of any Tkinter imports (like ``processing``) so it can be
unit-tested without a display. Editing a field rebuilds the ``InvoiceData``
(Pydantic re-coerces/validates the new value) and re-runs the *pure*
``validate_invoice`` against the retained raw PDF text — so grounding and the
other checks reflect the corrected value immediately. **No extraction / LLM call
is ever made here**, so editing never spends tokens.
"""
from dataclasses import replace
from typing import Any, get_args

from models import InvoiceData
from validation import validate_invoice

from .processing import InvoiceResult


def _is_nullable(field_name: str) -> bool:
    """Whether ``field_name`` accepts ``None`` (i.e. is declared ``Optional``).

    Used so that clearing an optional field in the UI stores ``None`` rather than
    an empty string.
    """
    annotation = InvoiceData.model_fields[field_name].annotation
    return type(None) in get_args(annotation)


def _coerce_input(field_name: str, text: str) -> Any:
    """Turn the raw editor string into the value handed to Pydantic.

    A blank string clears a nullable field to ``None``; otherwise the string is
    passed through and Pydantic coerces it to the field's type (ISO date,
    Decimal, int, ...), raising ``ValidationError`` if it can't.
    """
    if _is_nullable(field_name) and not text.strip():
        return None
    return text


def _revalidate(result: InvoiceResult, new_data: InvoiceData) -> InvoiceResult:
    """Re-run validation for ``new_data`` and return a fresh ``InvoiceResult``.

    The original ``result`` is left untouched; ``raw_text`` and ``extracted``
    carry over so further edits/reverts keep working.
    """
    validated = validate_invoice(new_data, result.raw_text or "")
    return replace(result, validated=validated)


def _rebuild(data: InvoiceData, field_name: str, value: Any) -> InvoiceData:
    """Return a copy of ``data`` with ``field_name`` set to ``value``.

    Goes through ``model_validate`` (not ``model_copy``) so the field validators
    and the model validator (e.g. "payment_date or payment_terms_days must be
    set") run on the edited value.
    """
    return InvoiceData.model_validate({**data.model_dump(), field_name: value})


def apply_field_edit(result: InvoiceResult, field_name: str, text: str) -> InvoiceResult:
    """Apply an edit to one field and re-validate.

    ``text`` is the raw string from the editor. Raises ``pydantic.ValidationError``
    if the value can't be coerced or breaks a model rule — the caller keeps the
    old value in that case. On success returns a new ``InvoiceResult`` with the
    updated data and freshly computed issues.
    """
    if result.validated is None:
        raise ValueError("cannot edit a result that has no extracted data")
    new_data = _rebuild(result.validated.data, field_name, _coerce_input(field_name, text))
    return _revalidate(result, new_data)


def revert_field(result: InvoiceResult, field_name: str) -> InvoiceResult:
    """Restore ``field_name`` to its originally extracted value and re-validate."""
    if result.validated is None or result.extracted is None:
        raise ValueError("cannot revert a result without an extraction snapshot")
    original = getattr(result.extracted, field_name)
    new_data = _rebuild(result.validated.data, field_name, original)
    return _revalidate(result, new_data)


def field_is_edited(result: InvoiceResult, field_name: str) -> bool:
    """Whether ``field_name``'s current value differs from the extracted one."""
    if result.validated is None or result.extracted is None:
        return False
    return getattr(result.validated.data, field_name) != getattr(result.extracted, field_name)
