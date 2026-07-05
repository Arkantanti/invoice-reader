# Invoice Reader

Extract structured data from PDF invoices with an LLM, then run a battery of
validation checks that flag anything uncertain for human review. Built for a
vendor / accounts-payable workflow, with the extracted data destined for the
[SaldeoSMART](https://saldeosmart.pl) accounting system.

## What it does

Given a PDF invoice, the pipeline:

1. **Extracts** the vendor/seller fields with an LLM (OpenAI, strict JSON schema)
   — company details, invoice number, dates, gross amount, currency, tax ID,
   IBAN, SWIFT/BIC.
2. **Reads** the PDF's raw text separately (`pdfplumber`) as ground truth.
3. **Validates** the extraction and produces a `ValidatedInvoice` with a list of
   issues and a `flagged_for_review` flag.

The validation layer is the core value-add — it catches LLM hallucinations and
malformed data so only invoices that genuinely need attention are surfaced:

- **Grounding** — every extracted string/amount must appear verbatim in the PDF
  text (tolerant of whitespace/punctuation), guarding against hallucinated values.
- **IBAN** — structural format, country-specific length, and ISO 7064 MOD-97
  checksum.
- **SWIFT/BIC** — structural validation; required when the IBAN is invalid.
- **Currency** — validated against the ISO 4217 code set.
- **Dates** — issue date not in the future, payment date not before issue date,
  and payment date consistent with `issue_date + payment_terms_days`.

Each issue carries a severity (`error` / `warning`); any `error` sets
`flagged_for_review = True`.

## Project layout

```
src/
  extraction/    LLM extraction (llm_extract) + raw text (text_extract)
  validation/    validate_invoice() + individual check functions (checks.py)
  models/        Pydantic models: InvoiceData, ValidationIssue, ValidatedInvoice
  pipeline/      process_invoice() — orchestrates extraction + validation
  ui/            Tkinter desktop app for batch review (see below)
  saldeo/        (planned) send processed invoices via the Saldeo API
  main.py        CLI entry point for a single invoice
tests/           pytest suite (extraction mocked — no live LLM calls)
sample_invoices/ drop your PDFs here (gitignored contents)
```

## Requirements & setup

The project runs in a **conda environment named `invoice-reader`** (Python 3.13).
Dependencies are listed in [`requirements.txt`](requirements.txt): `openai`,
`pdfplumber`, `pydantic`, `python-dotenv`, plus `Pillow` and `pypdfium2` for the
UI's PDF preview.

```bash
conda create -n invoice-reader python=3.13
conda activate invoice-reader
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root with your OpenAI key:

```
OPENAI_API_KEY=sk-...
```

The model is set in [`src/extraction/config.py`](src/extraction/config.py).

## Usage

### CLI — process one invoice

```bash
conda run -n invoice-reader python src/main.py path/to/invoice.pdf
```

Prints the extracted fields as JSON plus the validation result (flagged status and
any issues).

### Desktop UI — review a folder of invoices

A Tkinter app: pick a directory of PDFs, process them all, then page through the
results. Each invoice shows its extracted fields (flagged ones highlighted), the
list of validation issues, and the rendered PDF page side by side.

```bash
conda run -n invoice-reader python src/ui/__main__.py
```

To explore the interface **without spending any API tokens**, launch the demo,
which populates the app with fabricated results and locally-generated PDFs:

```bash
conda run -n invoice-reader python src/ui/demo.py
```

## Testing

```bash
conda run -n invoice-reader python -m pytest -q
```

The extraction layer is stubbed in tests, so the suite never makes live LLM calls.

> **Note on cost:** `process_invoice` sends each PDF to the OpenAI API, which costs
> tokens. Everything except actually processing real invoices (launching the UI,
> the demo, rendering previews, running tests) is free.

## Roadmap

- **`saldeo`** — submit processed/approved invoices via the Saldeo API.
- **UI** — draw highlight boxes over flagged field values directly on the
  rendered PDF page (groundwork: `pdfplumber` word boxes + `PageImage.draw_rect()`).
