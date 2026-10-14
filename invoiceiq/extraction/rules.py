"""Deterministic, label-anchored extractor for Colombian supplier invoices.

Each field gets a confidence: ~0.95 when anchored on an explicit label, lower when we
had to rely on position or a weak pattern. Low-confidence fields go to the LLM fallback
and, ultimately, to a human.
"""

import re
import unicodedata

from invoiceiq.extraction.colombia import normalize_nit, parse_cop_amount, parse_date
from invoiceiq.extraction.types import FIELD_NAMES, FieldResult

NIT_RE = re.compile(r"(\d{1,3}(?:\.\d{3}){2,4}|\d{6,10})\s*-\s*(\d)\b")
DATE_RE = (
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}"  # dd/mm/yyyy
    r"|\d{4}[/-]\d{1,2}[/-]\d{1,2}"  # yyyy-mm-dd
    r"|\d{1,2}\s+de\s+\w+\s+de\s+\d{4})"  # 2 de abril de 2026
)
FECHA_RE = re.compile(r"fecha([^:\d\n]{0,30}):?\s*" + DATE_RE, re.IGNORECASE)
NUMBER_RE = re.compile(
    r"factura[^\n]{0,40}?(?:no\.?|n°|nº|#|n[uú]mero)\s*:?\s*([A-Z]{1,6})?[\s-]?(\d{1,10})\b",
    re.IGNORECASE,
)
AMOUNT_RE = re.compile(r"(?:\$|COP)\s*\d[\d.,]*\d|\b\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?\b(?!\s*%)")

BUYER_HINTS = ("cliente", "adquiriente", "adquirente", "senores", "comprador", "facturar a")
SUPPLIER_LABEL = re.compile(r"^(?:emisor|proveedor|raz[oó]n social|vendedor)\s*:\s*(.+)$", re.I)
SUBTOTAL_HINT = re.compile(r"\b(sub\s?total|base gravable|valor antes de iva|total bruto)\b")
TOTAL_HINT = re.compile(r"\b(total a pagar|neto a pagar|valor total|total factura|total)\b")
LEGAL_SUFFIX = re.compile(r"\b(S\.?A\.?S\.?|LTDA\.?|S\.A\.|E\.U\.)", re.I)


def _plain(s: str) -> str:
    """Lower-case and strip accents for label matching."""
    nfkd = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _smart_title(name: str) -> str:
    if not name.isupper():
        return name
    words = [w if LEGAL_SUFFIX.fullmatch(w) else w.capitalize() for w in name.split()]
    return " ".join(words)


def _last_amount(line: str) -> tuple[str | None, float]:
    matches = AMOUNT_RE.findall(line)
    if not matches:
        return None, 0.0
    value = parse_cop_amount(matches[-1])
    return (f"{value:.2f}", 0.95) if value is not None else (None, 0.0)


def extract_supplier_nit(lines: list[str]) -> tuple[FieldResult, int | None]:
    candidates = []
    for i, line in enumerate(lines):
        for m in NIT_RE.finditer(line):
            prefix = _plain(line[: m.start()])
            if any(h in prefix for h in BUYER_HINTS):
                continue
            nit = normalize_nit(m.group(0))
            if nit:
                labeled = bool(re.search(r"nit\s*(emisor|proveedor|vendedor)", prefix))
                candidates.append((labeled, i, nit))
    if not candidates:
        return FieldResult(None, 0.0), None
    labeled = [c for c in candidates if c[0]]
    if labeled:
        _, idx, nit = labeled[0]
        return FieldResult(nit, 0.97), idx
    _, idx, nit = candidates[0]
    # An unlabeled NIT near the top of the document is almost always the issuer's.
    return FieldResult(nit, 0.9 if idx < max(4, len(lines) // 3) else 0.6), idx


def extract_supplier_name(lines: list[str], nit_line: int | None) -> FieldResult:
    for line in lines:
        if m := SUPPLIER_LABEL.match(line.strip()):
            return FieldResult(_smart_title(m.group(1).strip()), 0.95)
    if nit_line is not None:
        same_line = re.split(r"\bnit\.?\b", lines[nit_line], flags=re.I)[0].strip(" -:")
        if re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3}", same_line):
            return FieldResult(_smart_title(same_line), 0.85)
        if nit_line > 0:
            above = lines[nit_line - 1].strip()
            if re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3}", above) and ":" not in above:
                conf = 0.9 if LEGAL_SUFFIX.search(above) or nit_line == 1 else 0.82
                return FieldResult(_smart_title(above), conf)
    return FieldResult(None, 0.0)


def extract_invoice_number(text: str) -> FieldResult:
    if m := NUMBER_RE.search(text):
        prefix, number = m.group(1), m.group(2)
        value = f"{prefix.upper()}-{number}" if prefix else number
        return FieldResult(value, 0.95)
    if m := re.search(r"\b(?:no\.|n°)\s*([A-Z]{1,6}-?\d+)", text, re.I):
        return FieldResult(m.group(1).upper(), 0.6)
    return FieldResult(None, 0.0)


def extract_issue_date(text: str) -> FieldResult:
    best: FieldResult | None = None
    for m in FECHA_RE.finditer(text):
        label = _plain(m.group(1))
        if any(w in label for w in ("venc", "pago", "entrega", "limite")):
            continue
        parsed = parse_date(m.group(2))
        if not parsed:
            continue
        conf = 0.95 if any(w in label for w in ("emision", "expedicion", "factura")) else 0.9
        if best is None or conf > best.confidence:
            best = FieldResult(parsed.isoformat(), conf)
    return best or FieldResult(None, 0.0)


def extract_amounts(lines: list[str]) -> dict[str, FieldResult]:
    found: dict[str, FieldResult] = {}
    for line in lines:
        plain = _plain(line)
        value, conf = _last_amount(line)
        if value is None:
            continue
        if SUBTOTAL_HINT.search(plain):
            found.setdefault("subtotal", FieldResult(value, conf))
        elif re.search(r"\biva\b", plain):
            found.setdefault("iva", FieldResult(value, conf))
        elif TOTAL_HINT.search(plain) and not plain.startswith(("vr. total", "valor total")):
            found["total"] = FieldResult(value, conf)  # last "total" line wins
    return found


def extract_with_rules(text: str) -> dict[str, FieldResult]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    nit, nit_line = extract_supplier_nit(lines)
    results = {
        "invoice_number": extract_invoice_number(text),
        "issue_date": extract_issue_date(text),
        "supplier_name": extract_supplier_name(lines, nit_line),
        "supplier_nit": nit,
        **extract_amounts(lines),
    }
    return {name: results.get(name, FieldResult(None, 0.0)) for name in FIELD_NAMES}
