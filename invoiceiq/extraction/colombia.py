"""Colombian invoice primitives: NIT check digit (DIAN), COP amounts and dates."""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# DIAN "dígito de verificación" weights, applied from the rightmost digit of the base NIT.
_NIT_WEIGHTS = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)

SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def nit_check_digit(base: str) -> int:
    """Compute the DIAN check digit for a NIT base number (digits only, up to 15)."""
    digits = re.sub(r"\D", "", base)
    if not digits or len(digits) > len(_NIT_WEIGHTS):
        raise ValueError(f"invalid NIT base: {base!r}")
    total = sum(int(d) * w for d, w in zip(reversed(digits), _NIT_WEIGHTS, strict=False))
    remainder = total % 11
    return remainder if remainder in (0, 1) else 11 - remainder


def normalize_nit(raw: str) -> str | None:
    """'900.123.456-7' / '900123456 - 7' -> '900123456-7'. Returns None if no DV present."""
    m = re.fullmatch(r"\s*(\d{1,3}(?:[.\s]?\d{3}){2,4})\s*-\s*(\d)\s*", raw)
    if not m:
        return None
    base = re.sub(r"\D", "", m.group(1))
    return f"{base}-{m.group(2)}"


def is_valid_nit(nit: str) -> bool:
    normalized = normalize_nit(nit)
    if not normalized:
        return False
    base, dv = normalized.split("-")
    return nit_check_digit(base) == int(dv)


def parse_cop_amount(raw: str) -> Decimal | None:
    """Parse COP amounts: '$ 1.250.000,50', 'COP 1.487.500', '1250000', '1,250,000.50'."""
    s = re.sub(r"(?i)cop|\$|\s", "", raw)
    if not s or not re.fullmatch(r"-?[\d.,]+", s):
        return None
    last_dot, last_comma = s.rfind("."), s.rfind(",")
    decimal_sep = None
    if last_dot >= 0 and last_comma >= 0:
        decimal_sep = "," if last_comma > last_dot else "."
    elif last_comma >= 0 or last_dot >= 0:
        sep = "," if last_comma >= 0 else "."
        tail = s.rsplit(sep, 1)[1]
        # A single separator followed by exactly 3 digits is a thousands separator in COP.
        if s.count(sep) == 1 and len(tail) in (1, 2):
            decimal_sep = sep
    if decimal_sep:
        thousands = "." if decimal_sep == "," else ","
        s = s.replace(thousands, "").replace(decimal_sep, ".")
    else:
        s = s.replace(".", "").replace(",", "")
    try:
        return Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def parse_date(raw: str) -> date | None:
    """Accepts dd/mm/yyyy, dd-mm-yyyy, yyyy-mm-dd, yyyy/mm/dd and '2 de abril de 2026'."""
    raw = raw.strip().lower()
    try:
        if m := re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", raw):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", raw):
            return date(int(m[3]), int(m[2]), int(m[1]))
        if m := re.fullmatch(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+(?:de|del)\s+(\d{4})", raw):
            month = SPANISH_MONTHS.get(m[2])
            return date(int(m[3]), month, int(m[1])) if month else None
    except ValueError:
        return None
    return None


def format_cop(value: Decimal) -> str:
    """Decimal('1487500.5') -> '$ 1.487.500,50' (display only)."""
    whole, frac = f"{value:,.2f}".split(".")
    return f"$ {whole.replace(',', '.')},{frac}"
