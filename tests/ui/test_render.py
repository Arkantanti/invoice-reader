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


def test_render_pages_to_width_missing_file_returns_empty_list():
    assert render.render_pages_to_width("does-not-exist.pdf", 400) == []


def test_render_pages_to_width_nonpositive_width_returns_empty_list():
    assert render.render_pages_to_width("whatever.pdf", 0) == []


@pytest.mark.skipif(not render.RENDER_AVAILABLE, reason="pypdfium2 not installed")
def test_render_pages_to_width_renders_all_pages_at_target_width(tmp_path):
    pdf_path = _make_pdf(tmp_path / "three.pdf", pages=3)

    images = render.render_pages_to_width(pdf_path, 300)

    assert len(images) == 3
    assert all(isinstance(im, Image.Image) for im in images)
    # Each page is rasterized to (about) the requested pixel width.
    assert all(abs(im.width - 300) <= 2 for im in images)


@pytest.mark.skipif(not render.RENDER_AVAILABLE, reason="pypdfium2 not installed")
def test_render_pages_to_width_scales_with_requested_width(tmp_path):
    pdf_path = _make_pdf(tmp_path / "one.pdf")

    small = render.render_pages_to_width(pdf_path, 200)[0]
    large = render.render_pages_to_width(pdf_path, 600)[0]

    assert large.width > small.width  # re-rendered sharp at the larger size


@pytest.mark.skipif(not render.RENDER_AVAILABLE, reason="pypdfium2 not installed")
def test_render_pages_to_width_supersample_keeps_target_width(tmp_path):
    # Supersampling raises internal render resolution but the output is still
    # exactly the requested display width (only the antialiasing quality differs).
    pdf_path = _make_pdf(tmp_path / "one.pdf")

    plain = render.render_pages_to_width(pdf_path, 250, supersample=1.0)[0]
    sharp = render.render_pages_to_width(pdf_path, 250, supersample=3.0)[0]

    assert plain.width == 250
    assert sharp.width == 250
    assert sharp.size == plain.size
