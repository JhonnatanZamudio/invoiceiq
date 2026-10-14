from dataclasses import dataclass
from typing import Literal

FIELD_NAMES = (
    "invoice_number",
    "issue_date",
    "supplier_name",
    "supplier_nit",
    "subtotal",
    "iva",
    "total",
)
AMOUNT_FIELDS = ("subtotal", "iva", "total")

Source = Literal["rules", "llm", "human"]


@dataclass
class FieldResult:
    value: str | None  # normalised: dates ISO, NIT "base-dv", amounts "1234.50"
    confidence: float
    source: Source = "rules"


@dataclass(frozen=True)
class Issue:
    code: str  # nit_invalid | totals_mismatch | date_future | duplicate | iva_rate | ...
    message: str  # Spanish, shown in the UI
    field: str | None = None
    severity: Literal["error", "warning"] = "error"

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "severity": self.severity,
        }
