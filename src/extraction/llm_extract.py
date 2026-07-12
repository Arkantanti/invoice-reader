import base64
from pathlib import Path
from openai import OpenAI

from models.invoice_model import ExtractedInvoice
from .config import OPENAI_API_KEY, OPENAI_MODEL

from typing import Any, cast

client = OpenAI(api_key=OPENAI_API_KEY)

EXTRACTION_PROMPT = """You are an invoice data extraction assistant. This invoice is addressed to {your_company_name} (the buyer). Extract only the vendor/seller's details — the company issuing the invoice and requesting payment — not the buyer's details. Extract text fields (names, addresses, invoice number, tax ID) exactly as they appear on the invoice. For the bank account, extract the vendor's IBAN if present, otherwise the local account number as printed. Do not infer or calculate values that are not explicitly present.

Normalize these fields to a canonical machine format, using the invoice's own locale to interpret them correctly:
- issue_date and payment_date: output as ISO 8601 YYYY-MM-DD. Read the invoice's date convention to resolve day/month order (e.g. a European invoice showing 09/06/2026 means 2026-06-09).
- amount: a plain decimal with '.' as the decimal separator and NO thousands separators or currency symbols (e.g. 10.400,00 becomes 10400.00; keep the cents).
- currency: the ISO 4217 three-letter uppercase code (e.g. PLN, EUR, USD, GBP). Convert a currency symbol or local name to its code when it is unambiguous (e.g. zł -> PLN, € -> EUR, $ -> USD). If the currency genuinely cannot be determined, leave it as written on the invoice rather than guessing."""

def to_strict_schema(model: type[ExtractedInvoice]) -> dict:
    """Patch a Pydantic-generated schema to satisfy OpenAI's strict json_schema mode."""
    schema = model.model_json_schema()
    schema["additionalProperties"] = False
    schema["required"] = list(schema["properties"].keys())
    for prop in schema["properties"].values():
        prop.pop("default", None)
    return schema


def extract_invoice_data(pdf_path: str) -> ExtractedInvoice:
    """Send a PDF invoice to the LLM (inline base64) and return an ExtractedInvoice."""
    pdf_bytes = Path(pdf_path).read_bytes()
    b64_pdf = base64.b64encode(pdf_bytes).decode("utf-8")

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=cast(Any, [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": EXTRACTION_PROMPT},
                    {
                        "type": "input_file",
                        "filename": Path(pdf_path).name,
                        "file_data": f"data:application/pdf;base64,{b64_pdf}",
                    },
                ],
            }
        ]),
        text= cast(Any, {
            "format": {
                "type": "json_schema",
                "name": "invoice_data",
                "schema": to_strict_schema(ExtractedInvoice),
                "strict": True,
            }
        }),
    )

    return ExtractedInvoice.model_validate_json(response.output_text)