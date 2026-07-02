# tests/test_setup.py
def test_key_dependencies_installed():
    """Confirms core third-party packages are installed correctly."""
    import anthropic
    import pdfplumber
    import dotenv