from pydantic import BaseModel, model_validator, ConfigDict, Field
from datetime import date
from decimal import Decimal
from typing import Optional

class InvoiceData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(description="Name of the vendor/seller company issuing the invoice, not the buyer.")
    company_address: str = Field(description="Address of the vendor/seller company, not the buyer.")
    invoice_number: str
    issue_date: date = Field(description="Date the invoice was issued, not the delivery or due date.")
    payment_date: Optional[date] = Field(default=None, description="Payment due date, if stated explicitly on the invoice.")
    payment_terms_days: Optional[int] = Field(default=None, description="Payment term in days from the issue date, if stated (e.g. 'Net 30').")
    amount: Decimal = Field(json_schema_extra={"type": "string"}, description="Total gross amount due (including tax), not the net/subtotal amount.")
    currency: Optional[str] = None
    swift_bic: Optional[str] = Field(default=None, description="Vendor's SWIFT/BIC code, if present.")
    tax_id: str = Field(description="Tax ID of the vendor/seller company, not the buyer.")
    iban: str = Field(description="Vendor's bank account IBAN for receiving payment.")

    @model_validator(mode="after")
    def check_payment_info(self):
        if self.payment_date is None and self.payment_terms_days is None:
            raise ValueError("Either payment_date or payment_terms_days must be set")
        return self
