import json

import httpx

from invoiceiq.config import Settings
from invoiceiq.extraction.llm import (
    AnthropicProvider,
    FakeProvider,
    LLMExtraction,
    OpenAIProvider,
    build_provider,
)
from invoiceiq.extraction.pipeline import apply_llm_fallback
from invoiceiq.extraction.types import FieldResult

STRONG = FieldResult("FE-1", 0.95)


def _fields(**weak):
    base = {
        n: STRONG
        for n in (
            "invoice_number",
            "issue_date",
            "supplier_name",
            "supplier_nit",
            "subtotal",
            "iva",
            "total",
        )
    }
    return {**base, **weak}


def test_fallback_only_asks_for_weak_fields_and_caps_confidence():
    provider = FakeProvider(
        {
            "issue_date": "05.03.2026",
            "total": "$ 2.856.000",
            "invoice_number": "SHOULD-NOT-BE-USED",
            "confidence": 0.99,
        }
    )
    fields = _fields(issue_date=FieldResult(None, 0.0), total=FieldResult("1", 0.4))
    merged, requested, filled = apply_llm_fallback("txt", fields, provider, 0.8, 0.7)
    assert provider.calls == [["issue_date", "total"]]
    assert requested == ["issue_date", "total"]
    assert merged["invoice_number"] is STRONG
    # "05.03.2026" fails schema validation and is dropped; the valid total is kept.
    assert filled == ["total"]
    assert merged["issue_date"].value is None
    assert merged["total"] == FieldResult("2856000.00", 0.7, "llm")


def test_fake_provider_default_fills_nothing():
    merged, requested, filled = apply_llm_fallback(
        "txt", _fields(total=FieldResult(None, 0)), FakeProvider(), 0.8, 0.7
    )
    assert requested == ["total"] and filled == [] and merged["total"].value is None


def test_schema_normalizes_and_rejects():
    ok = LLMExtraction.model_validate({"supplier_nit": "900.123.456-8", "issue_date": "2026-03-05"})
    assert ok.supplier_nit == "900123456-8" and ok.issue_date == "2026-03-05"
    assert LLMExtraction.model_validate({"unexpected": "x"}).model_dump(exclude={"confidence"}) == {
        k: None
        for k in (
            "invoice_number",
            "issue_date",
            "supplier_name",
            "supplier_nit",
            "subtotal",
            "iva",
            "total",
        )
    }


def test_anthropic_provider_parses_json_via_mock_transport():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"] = str(request.url), json.loads(request.content)
        text = 'Aquí está:\n```json\n{"invoice_number": "DS-981", "confidence": 0.8}\n```'
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})

    provider = AnthropicProvider("test-key", transport=httpx.MockTransport(handler))
    out = provider.extract("Consecutivo DS 981", ["invoice_number"])
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert "invoice_number" in seen["body"]["messages"][0]["content"]
    assert out.invoice_number == "DS-981" and out.confidence == 0.8


def test_openai_provider_failure_returns_empty_result():
    provider = OpenAIProvider("k", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert provider.extract("x", ["total"]) == LLMExtraction()


def test_default_provider_is_offline_fake():
    assert isinstance(build_provider(Settings()), FakeProvider)
    # A real provider is only built with an explicit key AND provider choice.
    assert isinstance(build_provider(Settings(llm_provider="anthropic")), FakeProvider)
