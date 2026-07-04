from pydantic import BaseModel
from typing import Literal
from .invoice_model import InvoiceData

class ValidationIssue(BaseModel):
    field: str
    message: str
    severity: Literal["error", "warning"]

class ValidatedInvoice(BaseModel):
    data: InvoiceData
    grounding_ok: bool          # values found verbatim in raw PDF text
    issues: list[ValidationIssue] = []
    flagged_for_review: bool = False