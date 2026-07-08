"""Launch the review UI in a fully offline demo mode — NO LLM, NO tokens, ever.

Two things happen here:

1. A few `InvoiceResult`s are fabricated by hand (a clean one, a flagged one, and
   a processing-error one), with matching placeholder PDFs generated locally so
   the fields/issues panes and the preview have content to show.
2. The real pipeline is **stubbed out**: ``ui.processing.process_invoice`` is
   replaced with a no-network placeholder. So the toolbar works — you can
   "Choose PDF"/"Choose folder" real invoices and press **Process** — and each
   PDF is loaded and rendered in the viewer *without* any extraction or LLM call.
   Clicking Process in the demo can never spend tokens.

Run: ``conda run -n invoice-reader python src/ui/demo.py``
"""
import os
import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PIL import Image, ImageDraw  # noqa: E402

from models import InvoiceData, ValidatedInvoice, ValidationIssue  # noqa: E402
from ui import processing  # noqa: E402
from ui.app import InvoiceReviewApp  # noqa: E402
from ui.processing import InvoiceResult  # noqa: E402


def _demo_process(pdf_path: str) -> ValidatedInvoice:
    """Stand-in for ``process_invoice`` in the demo — no extraction, no LLM call.

    Returns a placeholder so the selected/processed PDF still shows up in the list
    and renders in the preview pane; it does not read or interpret the document.
    """
    data = InvoiceData(
        company_name="(demo — not processed)",
        company_address="—",
        invoice_number=Path(pdf_path).stem,
        issue_date=date.today(),
        payment_terms_days=0,
        amount=Decimal("0.00"),
        currency=None,
        tax_id="—",
        iban="—",
        swift_bic=None,
    )
    note = ValidationIssue(
        field="document",
        message="Demo mode: PDF loaded for preview only — no extraction or LLM call was made.",
        severity="warning",
    )
    return ValidatedInvoice(data=data, issues=[note], flagged_for_review=False)


def _result(pdf: Path, data: InvoiceData, issues: list) -> InvoiceResult:
    flagged = any(i.severity == "error" for i in issues)
    validated = ValidatedInvoice(data=data, issues=issues, flagged_for_review=flagged)
    return InvoiceResult(path=pdf, validated=validated)


def _make_pdf(path: Path, lines: list[str]) -> None:
    """Write a simple A4-ish white page with text so the preview has content."""
    img = Image.new("RGB", (827, 1169), "white")
    draw = ImageDraw.Draw(img)
    y = 80
    for line in lines:
        draw.text((70, y), line, fill="black")
        y += 34
    img.save(path, "PDF")


def _clean_result(folder: Path) -> InvoiceResult:
    pdf = folder / "acme_ok.pdf"
    _make_pdf(pdf, [
        "ACME Sp. z o.o.", "ul. Testowa 1, 00-001 Warszawa", "",
        "Invoice No: FV/2026/07/001", "Issue date: 2026-07-01",
        "Amount due: 1230.00 PLN", "IBAN: PL61109010140000071219812874",
        "NIP: 5260001246",
    ])
    data = InvoiceData(
        company_name="ACME Sp. z o.o.",
        company_address="ul. Testowa 1, 00-001 Warszawa",
        invoice_number="FV/2026/07/001",
        issue_date=date(2026, 7, 1),
        payment_terms_days=14,
        amount=Decimal("1230.00"),
        currency="PLN",
        tax_id="5260001246",
        iban="PL61109010140000071219812874",
    )
    return _result(pdf, data, [])


def _flagged_result(folder: Path) -> InvoiceResult:
    pdf = folder / "globex_flagged.pdf"
    _make_pdf(pdf, [
        "Globex International Ltd", "42 Trade Street, London", "",
        "Invoice: INV-2026-5567", "Issued: 2026-07-03",
        "Total: 8,940.00", "IBAN: GB29NWBK60161331926819",
        "SWIFT: NWBKGB2Lxxx", "VAT: GB123456789",
    ])
    data = InvoiceData(
        company_name="Globex International Ltd",
        company_address="42 Trade Street, London",
        invoice_number="INV-2026-5567",
        issue_date=date(2026, 7, 3),
        payment_date=date(2026, 8, 2),
        payment_terms_days=14,
        amount=Decimal("8940.00"),
        currency="gbp",
        tax_id="GB123456789",
        iban="GB29NWBK60161331926819",
        swift_bic="NWBKGB2Lxxx",
    )
    issues = [
        ValidationIssue(field="amount", message="amount not found verbatim in source PDF text", severity="error"),
        ValidationIssue(field="payment_date", message="payment_date does not match issue_date + payment_terms_days", severity="error"),
        ValidationIssue(field="swift_bic", message="SWIFT/BIC 'NWBKGB2Lxxx' is not correctly formatted", severity="warning"),
        ValidationIssue(field="currency", message="'gbp' is not a recognized ISO 4217 currency code", severity="warning"),
        ValidationIssue(field="bank_account_number", message="IBAN country code is not in the known list", severity="warning"),
    ]
    return _result(pdf, data, issues)


def _error_result(folder: Path) -> InvoiceResult:
    pdf = folder / "scan_broken.pdf"
    _make_pdf(pdf, ["(scanned image with no extractable text)"])
    return InvoiceResult(path=pdf, error="RuntimeError: simulated extraction failure (demo)")


def main() -> None:
    # Disable the real pipeline so "Process" can never reach the LLM. The worker
    # thread calls processing.process_pdf -> process_invoice; swap the latter.
    processing.process_invoice = _demo_process

    folder = Path(tempfile.mkdtemp(prefix="invoice_ui_demo_"))
    results = [_clean_result(folder), _flagged_result(folder), _error_result(folder)]

    app = InvoiceReviewApp()
    app.title("Invoice Reader — DEMO (no LLM)")
    app.folder_var.set("DEMO — Process is stubbed; buttons load PDFs for preview only")
    for result in results:
        app._append_result(result)
    app.mainloop()


if __name__ == "__main__":
    main()
