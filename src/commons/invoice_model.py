from pydantic import BaseModel, model_validator
from datetime import date
from decimal import Decimal
from typing import Optional

class InvoiceData(BaseModel):
    company_name: str
    company_address: str
    invoice_number: str
    issue_date: date
    payment_date: Optional[date] = None
    payment_terms_days: Optional[int] = None
    amount: Decimal
    currency: str  # validated against ISO 4217 list downstream
    iban: str  # validated via mod-97 downstream
    tax_id: str  # NIP / USCC / VAT number depending on vendor country

    @model_validator(mode="after")
    def check_payment_info(self):
        if self.payment_date is None and self.payment_terms_days is None:
            raise ValueError("Either payment_date or payment_terms_days must be set")
        return self
