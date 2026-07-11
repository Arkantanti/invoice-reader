from pydantic import BaseModel
from typing import Literal
from .invoice_model import ExtractedInvoice

class ValidationIssue(BaseModel):
    field: str
    message: str
    severity: Literal["error", "warning"]

class ValidatedInvoice(BaseModel):
    data: ExtractedInvoice
    issues: list[ValidationIssue] = []
    flagged_for_review: bool = False