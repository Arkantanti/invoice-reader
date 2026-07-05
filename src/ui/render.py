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
    import pypdfium2  # noqa: F401  (presence check for the render backend)

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
