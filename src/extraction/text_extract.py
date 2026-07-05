import pdfplumber

def extract_text(pdf_path: str) -> str:
    """Extract raw text from all pages of a PDF, concatenated."""
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)