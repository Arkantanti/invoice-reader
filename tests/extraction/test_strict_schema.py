
from extraction.llm_extract import to_strict_schema
from models.invoice_model import InvoiceData

def test_additional_properties_is_false():
    schema = to_strict_schema(InvoiceData)
    assert schema["additionalProperties"] is False


def test_all_properties_are_required():
    schema = to_strict_schema(InvoiceData)
    assert set(schema["required"]) == set(schema["properties"].keys())


def test_no_property_has_default_key():
    schema = to_strict_schema(InvoiceData)
    for field_name, prop in schema["properties"].items():
        assert "default" not in prop, f"'{field_name}' still has a default key"


def test_original_pydantic_schema_is_not_mutated():
    """Guards against to_strict_schema mutating a cached/shared schema dict
    that model_json_schema() might return on repeated calls."""
    schema_before = InvoiceData.model_json_schema()
    optional_fields_before = {
        k for k, v in schema_before["properties"].items() if "default" in v
    }
    assert optional_fields_before, "expected at least one Optional field with a default in the raw schema"

    to_strict_schema(InvoiceData)

    schema_after = InvoiceData.model_json_schema()
    optional_fields_after = {
        k for k, v in schema_after["properties"].items() if "default" in v
    }
    assert optional_fields_before == optional_fields_after


def test_required_field_count_matches_property_count():
    schema = to_strict_schema(InvoiceData)
    assert len(schema["required"]) == len(schema["properties"])