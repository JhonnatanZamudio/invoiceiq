"""PDF bytes -> text -> rules -> LLM fallback (only weak fields) -> validation."""

import io
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pdfplumber

from invoiceiq.extraction.llm import LLMProvider
from invoiceiq.extraction.rules import extract_with_rules
from invoiceiq.extraction.types import FIELD_NAMES, FieldResult, Issue
from invoiceiq.extraction.validation import DuplicateCheck, validate


@dataclass
class PipelineResult:
    text: str
    fields: dict[str, FieldResult]
    rules_fields: dict[str, FieldResult]
    issues: list[Issue]
    llm_requested: list[str] = field(default_factory=list)  # weak fields sent to the LLM
    llm_fields: list[str] = field(default_factory=list)  # fields the LLM actually filled
    elapsed_ms: float = 0.0

    @property
    def needs_review(self) -> bool:
        return bool(self.issues)


def pdf_to_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def apply_llm_fallback(
    text: str,
    fields: dict[str, FieldResult],
    provider: LLMProvider,
    threshold: float,
    confidence_cap: float,
) -> tuple[dict[str, FieldResult], list[str], list[str]]:
    """Returns (merged fields, fields requested from the LLM, fields it filled)."""
    weak = [n for n in FIELD_NAMES if not fields[n].value or fields[n].confidence < threshold]
    if not weak:
        return fields, [], []
    answer = provider.extract(text, weak)
    merged, filled = dict(fields), []
    for name in weak:
        value = getattr(answer, name)
        if value:
            # Capped below the review threshold: LLM output is always confirmed by a human.
            merged[name] = FieldResult(value, min(answer.confidence, confidence_cap), "llm")
            filled.append(name)
    return merged, weak, filled


def run_pipeline(
    pdf_bytes: bytes,
    *,
    provider: LLMProvider,
    is_duplicate: DuplicateCheck,
    today: date,
    review_threshold: float = 0.8,
    llm_confidence_cap: float = 0.7,
    tolerance: Decimal = Decimal("1"),
) -> PipelineResult:
    start = time.perf_counter()
    text = pdf_to_text(pdf_bytes)
    rules_fields = extract_with_rules(text)
    fields, requested, filled = apply_llm_fallback(
        text, rules_fields, provider, review_threshold, llm_confidence_cap
    )
    issues = validate(
        fields,
        today=today,
        is_duplicate=is_duplicate,
        review_threshold=review_threshold,
        tolerance=tolerance,
    )
    elapsed = (time.perf_counter() - start) * 1000
    return PipelineResult(text, fields, rules_fields, issues, requested, filled, elapsed)
