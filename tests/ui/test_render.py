"""Tests for the PDF render helper.

Test PDFs are generated locally with Pillow (no LLM, no network). The positive
render tests are skipped when the pypdfium2 backend isn't installed.
"""
import pytest
from PIL import Image

from ui import render


def _make_pdf(path, pages=1, size=(120, 160)) -> str:
    imgs = [Image.new("RGB", size, "white") for _ in range(pages)]
    imgs[0].save(path, "PDF", save_all=True, append_images=imgs[1:])
    return str(path)


def test_render_missing_file_returns_none():
    assert render.render_page("does-not-exist.pdf") is None


def test_page_count_missing_file_is_zero():
    assert render.page_count("does-not-exist.pdf") == 0


@pytest.mark.skipif(not render.RENDER_AVAILABLE, reason="pypdfium2 not installed")
def test_render_page_returns_image(tmp_path):
    pdf_path = _make_pdf(tmp_path / "one.pdf")

    image = render.render_page(pdf_path, 0)

    assert isinstance(image, Image.Image)
    assert image.width > 0 and image.height > 0


@pytest.mark.skipif(not render.RENDER_AVAILABLE, reason="pypdfium2 not installed")
def test_render_page_out_of_range_returns_none(tmp_path):
    pdf_path = _make_pdf(tmp_path / "one.pdf")

    assert render.render_page(pdf_path, 5) is None


@pytest.mark.skipif(not render.RENDER_AVAILABLE, reason="pypdfium2 not installed")
def test_page_count(tmp_path):
    pdf_path = _make_pdf(tmp_path / "three.pdf", pages=3)

    assert render.page_count(pdf_path) == 3
