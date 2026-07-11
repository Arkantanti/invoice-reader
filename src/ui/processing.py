"""Headless processing layer for the review UI.

Deliberately free of any Tkinter imports so it can be unit-tested without a
display and without hitting the LLM (tests stub out ``process_invoice``).
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from extraction import extract_text
from models import ExtractedInvoice, ValidatedInvoice
from pipeline import process_invoice


@dataclass
class InvoiceResult:
    """Outcome of processing a single PDF.

    Exactly one of ``validated`` / ``error`` is meaningful: on success
    ``validated`` holds the ``ValidatedInvoice``; on failure ``error`` holds a
    human-readable message and ``validated`` stays ``None``.

    ``raw_text`` and ``extracted`` support in-app editing: the raw PDF text is
    the ground truth grounding re-checks against after an edit, and ``extracted``
    is an immutable snapshot of the original LLM extraction so any field can be
    reverted to what the model produced. Both are only populated on success.
    """

    path: Path
    validated: Optional[ValidatedInvoice] = None
    error: Optional[str] = None
    raw_text: Optional[str] = None
    extracted: Optional[ExtractedInvoice] = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def status(self) -> str:
        """One of ``"ok"``, ``"flagged"`` or ``"error"``."""
        if self.error is not None:
            return "error"
        if self.validated is not None and self.validated.flagged_for_review:
            return "flagged"
        return "ok"


def find_pdfs(directory: str) -> list[Path]:
    """Return the PDF files directly inside ``directory``, sorted by name.

    Deduplicated because a case-insensitive filesystem (Windows) can match the
    same file under both ``*.pdf`` and ``*.PDF`` globs.
    """
    base = Path(directory)
    matches = {p.resolve() for p in base.glob("*.pdf")}
    matches |= {p.resolve() for p in base.glob("*.PDF")}
    return sorted(matches, key=lambda p: p.name.lower())


def process_pdf(path: Path) -> InvoiceResult:
    """Run the extraction+validation pipeline for one PDF, never raising.

    Any failure (bad PDF, network/LLM error, validation error) is captured on
    the returned ``InvoiceResult`` so a single bad file can't abort a batch.
    """
    try:
        validated = process_invoice(str(path))
        # Keep the raw text (ground truth for re-grounding after an edit) and a
        # snapshot of the original extraction (for per-field revert). Reading the
        # text again is pdfplumber-only — no LLM, no tokens.
        raw_text = extract_text(str(path))
        return InvoiceResult(
            path=path,
            validated=validated,
            raw_text=raw_text,
            extracted=validated.data,
        )
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        return InvoiceResult(path=path, error=f"{type(exc).__name__}: {exc}")
