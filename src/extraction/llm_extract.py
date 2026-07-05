import base64
from pathlib import Path
from openai import OpenAI

from commons.invoice_model import InvoiceData
from config import OPENAI_API_KEY, OPENAI_MODEL

from typing import Any, cast

client = OpenAI(api_key=OPENAI_API_KEY)

EXTRACTION_PROMPT = """You are an invoice data extraction assistant. This invoice is addressed to {your_company_name} (the buyer). Extract only the vendor/seller's details — the company issuing the invoice and requesting payment — not the buyer's details. Extract fields exactly as they appear on the invoice. Do not infer or calculate values that are not explicitly present."""

def to_strict_schema(model: type[InvoiceData]) -> dict:
    """Patch a Pydantic-generated schema to satisfy OpenAI's strict json_schema mode."""
    schema = model.model_json_schema()
    schema["additionalProperties"] = False
    schema["required"] = list(schema["properties"].keys())
    for prop in schema["properties"].values():
        prop.pop("default", None)
    return schema


def extract_invoice_data(pdf_path: str) -> InvoiceData:
    """Send a PDF invoice to the LLM (inline base64) and return structured InvoiceData."""
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
                "schema": to_strict_schema(InvoiceData),
                "strict": True,
            }
        }),
    )

    return InvoiceData.model_validate_json(response.output_text)