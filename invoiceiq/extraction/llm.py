"""LLM fallback for fields the rule extractor could not resolve with confidence.

Providers return free-form text; we only trust what survives Pydantic validation
(NIT format, parsable dates/amounts). Network providers are opt-in via settings and
call the vendors' public endpoints directly; the default FakeProvider never touches
the network, which keeps tests, CI and the benchmark deterministic.
"""

import json
import logging
import re
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from invoiceiq.config import Settings
from invoiceiq.extraction.colombia import normalize_nit, parse_cop_amount, parse_date

log = logging.getLogger(__name__)


class LLMExtraction(BaseModel):
    """Schema the model must answer with. Unknown keys are dropped, bad values rejected."""

    model_config = ConfigDict(extra="ignore")

    invoice_number: str | None = Field(None, max_length=50)
    issue_date: str | None = None
    supplier_name: str | None = Field(None, max_length=200)
    supplier_nit: str | None = None
    subtotal: str | None = None
    iva: str | None = None
    total: str | None = None
    confidence: float = Field(0.5, ge=0.0, le=1.0)

    @field_validator("issue_date", mode="before")
    @classmethod
    def _date(cls, v: Any) -> str | None:
        if v in (None, ""):
            return None
        parsed = parse_date(str(v))
        if parsed is None:
            raise ValueError("unparseable date")
        return parsed.isoformat()

    @field_validator("supplier_nit", mode="before")
    @classmethod
    def _nit(cls, v: Any) -> str | None:
        if v in (None, ""):
            return None
        nit = normalize_nit(str(v))
        if nit is None:
            raise ValueError("NIT must include check digit, e.g. 900123456-7")
        return nit

    @field_validator("subtotal", "iva", "total", mode="before")
    @classmethod
    def _amount(cls, v: Any) -> str | None:
        if v in (None, ""):
            return None
        parsed = parse_cop_amount(str(v))
        if parsed is None:
            raise ValueError("unparseable amount")
        return f"{parsed:.2f}"


def parse_answer(data: dict[str, Any], fields: list[str]) -> LLMExtraction:
    """Validate field by field: one bad value is dropped instead of discarding the answer."""
    payload = {k: data[k] for k in [*fields, "confidence"] if k in data}
    while True:
        try:
            return LLMExtraction.model_validate(payload)
        except ValidationError as exc:
            bad = {str(e["loc"][0]) for e in exc.errors() if e["loc"]}
            if not bad & payload.keys():
                return LLMExtraction()
            for key in bad:
                payload.pop(key, None)


class LLMProvider(Protocol):
    name: str

    def extract(self, text: str, fields: list[str]) -> LLMExtraction: ...


class FakeProvider:
    """Deterministic offline provider. Returns `canned` values (empty by default)."""

    name = "fake"

    def __init__(self, canned: dict[str, Any] | None = None) -> None:
        self.canned = canned or {}
        self.calls: list[list[str]] = []

    def extract(self, text: str, fields: list[str]) -> LLMExtraction:
        self.calls.append(fields)
        return parse_answer(self.canned, fields)


PROMPT = """You extract data from Colombian supplier invoices (facturas).
Return ONLY a JSON object with these keys: {fields}, plus "confidence" (0-1).
Rules: dates as YYYY-MM-DD; supplier_nit is the ISSUER's NIT (not the client's) as
"digits-checkdigit"; amounts in COP as plain numbers with "." decimals; use null if absent.

Invoice text:
<<<
{text}
>>>"""


def _parse_json_object(raw: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    return json.loads(match.group(0)) if match else {}


class _HTTPProvider:
    name = "http"
    url = ""
    default_model = ""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model or self.default_model
        # trust_env=False: never pick up proxy/base-URL overrides from the environment.
        self.client = httpx.Client(transport=transport, timeout=timeout, trust_env=False)

    def _request(self, prompt: str) -> str:
        raise NotImplementedError

    def extract(self, text: str, fields: list[str]) -> LLMExtraction:
        prompt = PROMPT.format(fields=", ".join(fields), text=text[:8000])
        try:
            return parse_answer(_parse_json_object(self._request(prompt)), fields)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("%s fallback failed: %s", self.name, exc)
            return LLMExtraction()


class AnthropicProvider(_HTTPProvider):
    name = "anthropic"
    url = "https://api.anthropic.com/v1/messages"
    default_model = "claude-sonnet-4-5"

    def _request(self, prompt: str) -> str:
        resp = self.client.post(
            self.url,
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            json={
                "model": self.model,
                "max_tokens": 512,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        return "".join(b.get("text", "") for b in resp.json()["content"])


class OpenAIProvider(_HTTPProvider):
    name = "openai"
    url = "https://api.openai.com/v1/chat/completions"
    default_model = "gpt-4o-mini"

    def _request(self, prompt: str) -> str:
        resp = self.client.post(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake" or not settings.llm_api_key:
        return FakeProvider()
    cls = AnthropicProvider if settings.llm_provider == "anthropic" else OpenAIProvider
    return cls(settings.llm_api_key, settings.llm_model)
