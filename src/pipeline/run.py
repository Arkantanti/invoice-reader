from extraction import extract_invoice_data
from extraction import extract_text
from validation import validate_invoice
from models import ValidatedInvoice


def process_invoice(pdf_path: str) -> ValidatedInvoice:
    invoice_data = extract_invoice_data(pdf_path)
    raw_text = extract_text(pdf_path)
    return validate_invoice(invoice_data, raw_text)