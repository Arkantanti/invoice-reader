from pydantic import BaseModel, ConfigDict, Field
from typing import Optional


class ExtractedInvoice(BaseModel):
    """Permissive capture of whatever the LLM read off an invoice.

    Every field is an optional string — this is a data-transfer object, not a
    business-rules gate. It deliberately never raises on a missing or malformed
    value, so a single unreadable field can't wipe an otherwise good extraction:
    the LLM returns ``null`` for what it couldn't read, and it shows up as a
    blank, editable field. All required-ness, format and cross-field rules live
    in the validation layer (``validation.validate_invoice``), which reports them
    as ``ValidationIssue``s. Typed values (dates, amount) are parsed there.

    Dates are captured as ISO ``YYYY-MM-DD`` strings and the amount as a plain
    dot-decimal string (the extraction prompt normalizes to these), but they stay
    strings here — a string can't be "malformed" at the schema level.
    """

    model_config = ConfigDict(extra="forbid")

    company_name: Optional[str] = Field(default=None, description="Name of the vendor/seller company issuing the invoice, not the buyer.")
    company_address: Optional[str] = Field(default=None, description="Address of the vendor/seller company, not the buyer.")
    invoice_number: Optional[str] = Field(default=None, description="The invoice number/identifier.")
    issue_date: Optional[str] = Field(default=None, description="Date the invoice was issued (ISO 8601 YYYY-MM-DD), not the delivery or due date.")
    payment_date: Optional[str] = Field(default=None, description="Payment due date (ISO 8601 YYYY-MM-DD), if stated explicitly on the invoice.")
    payment_terms_days: Optional[str] = Field(default=None, description="Payment term in days from the issue date, if stated (e.g. 'Net 30').")
    amount: Optional[str] = Field(default=None, description="Total gross amount due (including tax) as a plain dot-decimal, not the net/subtotal.")
    currency: Optional[str] = Field(default=None, description="ISO 4217 three-letter currency code.")
    swift_bic: Optional[str] = Field(default=None, description="Vendor's SWIFT/BIC code, if present.")
    tax_id: Optional[str] = Field(default=None, description="Tax ID of the vendor/seller company, not the buyer.")
    iban: Optional[str] = Field(default=None, description="Vendor's bank account IBAN for receiving payment.")
