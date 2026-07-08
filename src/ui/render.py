"""Rasterize PDF pages to images for the preview pane.

No Tkinter here — this returns plain ``PIL.Image`` objects. Rendering goes
through ``pdfplumber.Page.to_image()``, whose backend is ``pypdfium2``. That
backend is imported lazily by pdfplumber, so text extraction works without it;
only the preview needs it. If it's missing (or a page fails to render) we return
``None`` and let the UI fall back to a "fields only" view rather than crash.
"""
from typing import Optional

import pdfplumber
from PIL import Image

try:  # pragma: no cover - depends on the runtime env
    import pypdfium2  # render backend (also used directly for width-targeted rendering)

    RENDER_AVAILABLE = True
except Exception:  # noqa: BLE001
    RENDER_AVAILABLE = False


def page_count(pdf_path: str) -> int:
    """Number of pages in the PDF (0 if it can't be opened)."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            return len(pdf.pages)
    except Exception:  # noqa: BLE001
        return 0


def render_page(pdf_path: str, page_index: int = 0, resolution: int = 150) -> Optional[Image.Image]:
    """Render one page to a ``PIL.Image``.

    Returns ``None`` (never raises) when the render backend is unavailable, the
    page index is out of range, or rendering otherwise fails.
    """
    if not RENDER_AVAILABLE:
        return None
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_index < 0 or page_index >= len(pdf.pages):
                return None
            page = pdf.pages[page_index]
            page_image = page.to_image(resolution=resolution)
            # Copy so the image outlives the closing of the pdfplumber context.
            return page_image.original.copy()
    except Exception:  # noqa: BLE001
        return None


def render_pages_to_width(
    pdf_path: str, width: int, supersample: float = 2.0, max_scale: float = 6.0
) -> list[Image.Image]:
    """Render every page as a ``PIL.Image`` exactly ``width`` pixels wide.

    Uses ``pypdfium2`` directly, rasterizing from the vector source. To sharpen
    the (necessarily small) preview, pages are rendered at ``supersample`` × the
    target width and then downsampled to ``width`` with a high-quality filter —
    this yields crisper antialiased text than rasterizing straight at the display
    size. ``max_scale`` caps the pixels-per-point ratio so a very wide pane can't
    trigger an enormous render (supersampling tapers off past that point).

    Returns an empty list (never raises) when the backend is unavailable or the
    PDF can't be rendered.
    """
    if not RENDER_AVAILABLE or width <= 0:
        return []
    try:
        pdf = pypdfium2.PdfDocument(pdf_path)
    except Exception:  # noqa: BLE001
        return []
    try:
        images = []
        for page in pdf:
            try:
                width_pt = page.get_size()[0]
                scale = min(width * supersample / width_pt, max_scale) if width_pt else 1.0
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                if image.width != width:  # downsample the supersampled render to target width
                    height = max(1, round(image.height * width / image.width))
                    image = image.resize((width, height), Image.Resampling.LANCZOS)
                # Copy so the PIL image doesn't alias the (soon-freed) bitmap buffer.
                images.append(image.copy())
                bitmap.close()
            finally:
                page.close()
        return images
    except Exception:  # noqa: BLE001
        return []
    finally:
        pdf.close()
