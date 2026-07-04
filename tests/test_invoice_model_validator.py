import pytest
from pydantic import ValidationError
from datetime import date
from decimal import Decimal

from commons.invoice_model import InvoiceData


def make_invoice(**overrides):
    """Helper: valid base fields, override payment fields per test."""
    base = dict(
        company_name="Shenzhen Example Co., Ltd.",
        company_address="123 Example Rd, Shenzhen, China",
        invoice_number="INV-2026-0001",
        issue_date=date(2026, 6, 1),
        amount=Decimal("1000.00"),
        currency="CNY",
        iban="DE44500105175407324931",
        tax_id="91440300MA5EXAMPLE",
    )
    base.update(overrides)
    return InvoiceData(**base)


def test_payment_date_only_is_valid():
    invoice = make_invoice(payment_date=date(2026, 6, 30), payment_terms_days=None)
    assert invoice.payment_date == date(2026, 6, 30)
    assert invoice.payment_terms_days is None


def test_payment_terms_days_only_is_valid():
    invoice = make_invoice(payment_date=None, payment_terms_days=30)
    assert invoice.payment_terms_days == 30
    assert invoice.payment_date is None


def test_both_payment_fields_missing_raises():
    with pytest.raises(ValidationError) as exc_info:
        make_invoice(payment_date=None, payment_terms_days=None)
    assert "Either payment_date or payment_terms_days must be set" in str(exc_info.value)


def test_both_payment_fields_set_currently_passes():
    """
    Documents current behavior: the validator only checks that not both
    are None — it does not currently forbid both being set.
    This test will need updating once that ambiguity is resolved.
    """
    invoice = make_invoice(payment_date=date(2026, 6, 30), payment_terms_days=30)
    assert invoice.payment_date == date(2026, 6, 30)
    assert invoice.payment_terms_days == 30