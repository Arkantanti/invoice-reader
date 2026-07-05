"""Tests for the UI processing layer.

`process_invoice` is always stubbed here — these tests never touch the network
or the LLM.
"""
from pathlib import Path
from types import SimpleNamespace

from ui import processing
from ui.processing import InvoiceResult, find_pdfs, process_pdf


def _touch(path: Path) -> None:
    path.write_bytes(b"%PDF-1.4\n")


def test_find_pdfs_sorted_and_filtered(tmp_path):
    _touch(tmp_path / "b.pdf")
    _touch(tmp_path / "a.pdf")
    (tmp_path / "notes.txt").write_text("nope")
    (tmp_path / "sub").mkdir()
    _touch(tmp_path / "sub" / "nested.pdf")  # not recursive

    found = [p.name for p in find_pdfs(str(tmp_path))]

    assert found == ["a.pdf", "b.pdf"]


def test_find_pdfs_deduplicates_case_variants(tmp_path):
    # On a case-insensitive filesystem *.pdf and *.PDF hit the same file.
    _touch(tmp_path / "invoice.pdf")

    found = find_pdfs(str(tmp_path))

    assert len(found) == 1


def test_status_ok():
    validated = SimpleNamespace(flagged_for_review=False)
    result = InvoiceResult(path=Path("x.pdf"), validated=validated)
    assert result.status == "ok"


def test_status_flagged():
    validated = SimpleNamespace(flagged_for_review=True)
    result = InvoiceResult(path=Path("x.pdf"), validated=validated)
    assert result.status == "flagged"


def test_status_error():
    result = InvoiceResult(path=Path("x.pdf"), error="boom")
    assert result.status == "error"
    assert result.name == "x.pdf"


def test_process_pdf_success(monkeypatch):
    sentinel = SimpleNamespace(flagged_for_review=False)
    monkeypatch.setattr(processing, "process_invoice", lambda path: sentinel)

    result = process_pdf(Path("whatever.pdf"))

    assert result.validated is sentinel
    assert result.error is None
    assert result.status == "ok"


def test_process_pdf_captures_errors(monkeypatch):
    def boom(path):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(processing, "process_invoice", boom)

    result = process_pdf(Path("whatever.pdf"))

    assert result.validated is None
    assert result.status == "error"
    assert "kaboom" in result.error
