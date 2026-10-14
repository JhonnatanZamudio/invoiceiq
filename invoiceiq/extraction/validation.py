"""Business validation. Any issue sends the invoice to human review with its reasons."""

from collections.abc import Callable, Mapping
from datetime import date
from decimal import Decimal

from invoiceiq.extraction.colombia import format_cop, is_valid_nit, nit_check_digit
from invoiceiq.extraction.types import FIELD_NAMES, FieldResult, Issue

ALLOWED_IVA_RATES = (Decimal("0"), Decimal("0.05"), Decimal("0.19"))
FIELD_LABELS = {
    "invoice_number": "Número de factura",
    "issue_date": "Fecha de emisión",
    "supplier_name": "Proveedor",
    "supplier_nit": "NIT del proveedor",
    "subtotal": "Subtotal",
    "iva": "IVA",
    "total": "Total",
}

DuplicateCheck = Callable[[str, str], bool]


def _dec(v: str | None) -> Decimal | None:
    return Decimal(v) if v not in (None, "") else None


def validate(
    fields: Mapping[str, FieldResult],
    *,
    today: date,
    is_duplicate: DuplicateCheck,
    review_threshold: float,
    tolerance: Decimal = Decimal("1"),
) -> list[Issue]:
    issues: list[Issue] = []
    get = {name: (fields[name].value if name in fields else None) for name in FIELD_NAMES}

    for name in FIELD_NAMES:
        f = fields.get(name)
        if f is None or not f.value:
            issues.append(Issue("missing_field", f"Falta: {FIELD_LABELS[name]}", name))
        elif f.source != "human" and f.confidence < review_threshold:
            issues.append(
                Issue(
                    "low_confidence",
                    f"Confianza baja en {FIELD_LABELS[name]} ({f.confidence:.0%})",
                    name,
                    "warning",
                )
            )

    if (nit := get["supplier_nit"]) and not is_valid_nit(nit):
        base = nit.split("-")[0]
        issues.append(
            Issue(
                "nit_invalid",
                f"Dígito de verificación inválido (esperado {nit_check_digit(base)})",
                "supplier_nit",
            )
        )

    subtotal, iva, total = _dec(get["subtotal"]), _dec(get["iva"]), _dec(get["total"])
    if subtotal is not None and iva is not None and total is not None:
        diff = subtotal + iva - total
        if abs(diff) > tolerance:
            issues.append(
                Issue(
                    "totals_mismatch",
                    f"Subtotal + IVA ≠ Total (diferencia {format_cop(diff)})",
                    "total",
                )
            )
        if subtotal > 0 and not any(
            abs(iva - subtotal * r) <= tolerance for r in ALLOWED_IVA_RATES
        ):
            rate = iva / subtotal * 100
            issues.append(
                Issue("iva_rate", f"IVA de {rate:.1f}% no corresponde a 0/5/19%", "iva", "warning")
            )

    if (issued := get["issue_date"]) and date.fromisoformat(issued) > today:
        issues.append(Issue("date_future", "La fecha de emisión está en el futuro", "issue_date"))

    if nit and get["invoice_number"] and is_duplicate(nit, get["invoice_number"]):
        issues.append(
            Issue(
                "duplicate",
                "Ya existe una factura con este número para este proveedor",
                "invoice_number",
            )
        )
    return issues
