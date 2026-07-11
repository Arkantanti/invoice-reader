import base64
from unittest.mock import MagicMock
import pytest
from extraction.llm_extract import extract_invoice_data


@pytest.fixture
def valid_invoice_json():
    return """{
        "company_name": "Shenzhen Widget Co",
        "company_address": "123 Factory Rd, Shenzhen",
        "invoice_number": "INV-2026-001",
        "issue_date": "2026-06-01",
        "payment_date": null,
        "payment_terms_days": "30",
        "amount": "1234.56",
        "currency": "USD",
        "iban": "DE89370400440532013000",
        "swift_bic": "COBADEFFXXX",
        "tax_id": "91440300MA5FXXXX"
    }"""


def test_extract_invoice_data_parses_valid_response(monkeypatch, tmp_path, valid_invoice_json):
    fake_pdf = tmp_path / "invoice.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake content")

    fake_response = MagicMock()
    fake_response.output_text = valid_invoice_json

    mock_create = MagicMock(return_value=fake_response)
    monkeypatch.setattr("extraction.llm_extract.client.responses.create", mock_create)

    result = extract_invoice_data(str(fake_pdf))

    assert result.company_name == "Shenzhen Widget Co"
    assert str(result.amount) == "1234.56"
    assert result.iban == "DE89370400440532013000"


def test_extract_invoice_data_sends_correct_model_and_schema(monkeypatch, tmp_path, valid_invoice_json):
    fake_pdf = tmp_path / "invoice.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake content")

    fake_response = MagicMock()
    fake_response.output_text = valid_invoice_json

    mock_create = MagicMock(return_value=fake_response)
    monkeypatch.setattr("extraction.llm_extract.client.responses.create", mock_create)

    extract_invoice_data(str(fake_pdf))

    _, kwargs = mock_create.call_args
    assert kwargs["text"]["format"]["strict"] is True
    assert kwargs["text"]["format"]["schema"]["additionalProperties"] is False


def test_extract_invoice_data_encodes_pdf_as_base64(monkeypatch, tmp_path, valid_invoice_json):
    pdf_bytes = b"%PDF-1.4 fake content"
    fake_pdf = tmp_path / "invoice.pdf"
    fake_pdf.write_bytes(pdf_bytes)

    fake_response = MagicMock()
    fake_response.output_text = valid_invoice_json

    mock_create = MagicMock(return_value=fake_response)
    monkeypatch.setattr("extraction.llm_extract.client.responses.create", mock_create)

    extract_invoice_data(str(fake_pdf))

    _, kwargs = mock_create.call_args
    sent_file_data = kwargs["input"][0]["content"][1]["file_data"]
    expected_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    assert sent_file_data == f"data:application/pdf;base64,{expected_b64}"


def test_extract_invoice_data_accepts_partial_response(monkeypatch, tmp_path):
    # Capture is permissive: a partial extraction must NOT raise (that's the
    # whole point — one unreadable field can't wipe the rest). Missing fields
    # come back as None and are flagged later by validation, not here.
    fake_pdf = tmp_path / "invoice.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake content")

    fake_response = MagicMock()
    fake_response.output_text = '{"company_name": "Only one field"}'

    mock_create = MagicMock(return_value=fake_response)
    monkeypatch.setattr("extraction.llm_extract.client.responses.create", mock_create)

    result = extract_invoice_data(str(fake_pdf))

    assert result.company_name == "Only one field"
    assert result.tax_id is None
    assert result.amount is None


def test_extract_invoice_data_raises_on_unknown_field(monkeypatch, tmp_path):
    # extra="forbid" still rejects unexpected keys (a schema/model mismatch),
    # even though missing keys are tolerated.
    fake_pdf = tmp_path / "invoice.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake content")

    fake_response = MagicMock()
    fake_response.output_text = '{"company_name": "x", "surprise_field": "y"}'

    mock_create = MagicMock(return_value=fake_response)
    monkeypatch.setattr("extraction.llm_extract.client.responses.create", mock_create)

    with pytest.raises(Exception):
        extract_invoice_data(str(fake_pdf))