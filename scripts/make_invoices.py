"""Generate clearly fictional Colombian-style supplier invoices + ground truth.

Usage: python scripts/make_invoices.py [output_dir]   (default: data/samples)

Three layouts (A: classic header, B: key/value box, C: compact receipt) and a mix of
deliberate problems: wrong NIT check digits, totals that don't add up, a duplicate
invoice number and a future-dated invoice.
"""

import json
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from invoiceiq.extraction.colombia import nit_check_digit

BUYER = ("Comercializadora Cliente Demo S.A.S.", "901234567")
MONTHS = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
CENT = Decimal("0.01")


@dataclass
class Spec:
    file: str
    template: str
    supplier: str
    nit_base: str
    number: str
    issued: date
    items: list[tuple[str, int, int]]  # description, qty, unit price (COP)
    iva_rate: Decimal = Decimal("0.19")
    bad_dv: bool = False
    total_delta: Decimal = Decimal("0")  # deliberately wrong printed total
    expected_reasons: list[str] = field(default_factory=list)


def money(value: Decimal, decimals: bool = True, prefix: str = "$ ") -> str:
    q = value.quantize(CENT if decimals else Decimal("1"), rounding=ROUND_HALF_UP)
    whole, _, frac = f"{q:,.2f}".partition(".")
    whole = whole.replace(",", ".")
    return f"{prefix}{whole},{frac}" if decimals else f"{prefix}{whole}"


def nit_text(base: str, dv: int) -> str:
    return f"{int(base):,}".replace(",", ".") + f"-{dv}"


SPECS = [
    Spec(
        "fe_andina_1023.pdf",
        "A",
        "Distribuidora Andina Demo S.A.S.",
        "900123456",
        "FE-1023",
        date(2026, 3, 15),
        [("Resma papel carta", 40, 18500), ("Toner laser negro", 3, 245000)],
    ),
    Spec(
        "fe_andina_1031.pdf",
        "A",
        "Distribuidora Andina Demo S.A.S.",
        "900123456",
        "FE-1031",
        date(2026, 4, 2),
        [("Archivador AZ oficio", 25, 9800), ("Silla ergonomica", 2, 689900)],
    ),
    Spec(
        "fe_caribe_220.pdf",
        "A",
        "Logística Caribe Ficticia Ltda.",
        "830456789",
        "LC-220",
        date(2026, 2, 27),
        [("Flete Barranquilla - Bogota", 1, 1850000)],
        bad_dv=True,
        expected_reasons=["nit_invalid"],
    ),
    Spec(
        "fe_montana_77.pdf",
        "A",
        "Café Montaña Ejemplo S.A.S.",
        "901555222",
        "CM-77",
        date(2026, 5, 9),
        [("Cafe tostado 500 g", 60, 21500), ("Filtros papel", 30, 6400)],
        total_delta=Decimal("15000"),
        expected_reasons=["totals_mismatch"],
    ),
    Spec(
        "fv_tecno_0458.pdf",
        "B",
        "Tecnología Pacífico Demo S.A.S.",
        "800987654",
        "FV-0458",
        date(2026, 3, 3),
        [("Licencia antivirus anual", 15, 89000), ("Soporte tecnico hora", 12, 120000)],
    ),
    Spec(
        "fv_tecno_0462.pdf",
        "B",
        "Tecnología Pacífico Demo S.A.S.",
        "800987654",
        "FV-0462",
        date(2026, 3, 20),
        [("Portatil 14 pulgadas", 2, 2890000)],
    ),
    Spec(
        "fv_aseo_1190.pdf",
        "B",
        "Aseo Total Ficticio S.A.S.",
        "900765432",
        "AT-1190",
        date(2026, 1, 18),
        [("Servicio de aseo mensual", 1, 2350000), ("Insumos de aseo", 1, 412000)],
        bad_dv=True,
        expected_reasons=["nit_invalid"],
    ),
    Spec(
        "fv_tecno_0458_dup.pdf",
        "B",
        "Tecnología Pacífico Demo S.A.S.",
        "800987654",
        "FV-0458",
        date(2026, 3, 3),
        [("Licencia antivirus anual", 15, 89000), ("Soporte tecnico hora", 12, 120000)],
        expected_reasons=["duplicate"],
    ),
    Spec(
        "setp_4521.pdf",
        "C",
        "Ferretería El Tornillo Demo",
        "79123456",
        "SETP-4521",
        date(2026, 4, 2),
        [("Tornillo drywall x100", 10, 12900), ("Taladro percutor", 1, 329000)],
    ),
    Spec(
        "setp_4533.pdf",
        "C",
        "Ferretería El Tornillo Demo",
        "79123456",
        "SETP-4533",
        date(2026, 4, 16),
        [("Cemento gris 50 kg", 20, 31500)],
        iva_rate=Decimal("0.05"),
    ),
    Spec(
        "pan_88.pdf",
        "C",
        "Panadería La Espiga Ficticia",
        "1020304050",
        "PE-88",
        date(2026, 2, 10),
        [("Refrigerios reunion", 45, 8900), ("Torta corporativa", 1, 95000)],
        total_delta=Decimal("-25000"),
        expected_reasons=["totals_mismatch"],
    ),
    Spec(
        "setp_4600.pdf",
        "C",
        "Ferretería El Tornillo Demo",
        "79123456",
        "SETP-4600",
        date(2031, 1, 15),
        [("Pintura blanca galon", 6, 64900)],
        expected_reasons=["date_future"],
    ),
    # Off-template "documento soporte": labels the rules were NOT written for (fallback path).
    Spec(
        "ds_creativos_981.pdf",
        "D",
        "Servicios Creativos Ejemplo",
        "1098765432",
        "DS-981",
        date(2026, 3, 5),
        [("Diseno de piezas graficas", 1, 2400000)],
        expected_reasons=["missing_field"],
    ),
]


def amounts(spec: Spec) -> tuple[Decimal, Decimal, Decimal]:
    subtotal = sum((Decimal(q) * Decimal(p) for _, q, p in spec.items), Decimal("0"))
    iva = (subtotal * spec.iva_rate).quantize(CENT, rounding=ROUND_HALF_UP)
    return subtotal, iva, subtotal + iva + spec.total_delta


def draw_items(c: Canvas, spec: Spec, y: float, decimals: bool) -> float:
    c.setFont("Helvetica-Bold", 9)
    for x, h in ((50, "Descripción"), (330, "Cant."), (390, "Vr. unitario"), (490, "Vr. total")):
        c.drawString(x, y, h)
    c.setFont("Helvetica", 9)
    for desc, qty, price in spec.items:
        y -= 16
        c.drawString(50, y, desc)
        c.drawRightString(355, y, str(qty))
        c.drawRightString(470, y, money(Decimal(price), decimals))
        c.drawRightString(560, y, money(Decimal(qty * price), decimals))
    return y


def footer(c: Canvas) -> None:
    c.setFont("Helvetica-Oblique", 7)
    c.setFillColor(colors.grey)
    c.drawString(50, 40, "Documento ficticio generado para demostración de InvoiceIQ. Sin validez.")
    c.setFillColor(colors.black)


def template_a(c: Canvas, spec: Spec, dv: int) -> None:
    sub, iva, total = amounts(spec)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 740, spec.supplier)
    c.setFont("Helvetica", 10)
    c.drawString(50, 724, f"NIT {nit_text(spec.nit_base, dv)}  -  Régimen común")
    c.drawString(50, 710, "Calle 10 # 20-30, Bogotá D.C.  Tel. 601 555 0100")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(330, 680, f"FACTURA ELECTRÓNICA DE VENTA No. {spec.number}")
    c.setFont("Helvetica", 10)
    c.drawString(330, 664, f"Fecha de emisión: {spec.issued:%d/%m/%Y}")
    due = spec.issued.replace(day=min(spec.issued.day, 28), month=spec.issued.month % 12 + 1)
    c.drawString(330, 650, f"Fecha de vencimiento: {due:%d/%m/%Y}")
    c.drawString(50, 664, f"Señores: {BUYER[0]}")
    c.drawString(50, 650, f"NIT cliente: {nit_text(BUYER[1], nit_check_digit(BUYER[1]))}")
    y = draw_items(c, spec, 610, decimals=True) - 30
    rate = int(spec.iva_rate * 100)
    for label, value in (("Subtotal", sub), (f"IVA {rate}%", iva), ("Total a pagar", total)):
        c.setFont("Helvetica-Bold" if label.startswith("Total") else "Helvetica", 10)
        c.drawString(380, y, label)
        c.drawRightString(560, y, money(value))
        y -= 16


def template_b(c: Canvas, spec: Spec, dv: int) -> None:
    sub, iva, total = amounts(spec)
    c.setFillColor(colors.HexColor("#0f3d5e"))
    c.rect(0, 720, 612, 72, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, 750, "FACTURA DE VENTA")
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 10)
    rows = [
        ("Emisor", spec.supplier),
        ("NIT emisor", nit_text(spec.nit_base, dv)),
        ("Factura N°", f"{spec.number}"),
        ("Fecha", spec.issued.isoformat()),
        ("Adquiriente", BUYER[0]),
        ("NIT adquiriente", nit_text(BUYER[1], nit_check_digit(BUYER[1]))),
    ]
    y = 690
    for label, value in rows:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, f"{label}:")
        c.setFont("Helvetica", 10)
        c.drawString(160, y, value)
        y -= 15
    y = draw_items(c, spec, y - 25, decimals=False) - 30
    c.rect(360, y - 40, 210, 58, stroke=1, fill=0)
    rate = int(spec.iva_rate * 100)
    for label, value in (("Base gravable", sub), (f"IVA ({rate}%)", iva), ("TOTAL", total)):
        c.drawString(370, y, label)
        c.drawRightString(560, y, money(value, decimals=False, prefix="COP "))
        y -= 16


def template_c(c: Canvas, spec: Spec, dv: int) -> None:
    sub, iva, total = amounts(spec)
    c.setFont("Courier-Bold", 13)
    c.drawString(50, 740, spec.supplier.upper())
    c.setFont("Courier", 10)
    c.drawString(50, 726, f"Nit. {nit_text(spec.nit_base, dv)}")
    c.drawString(50, 712, "Persona natural - Responsable de IVA")
    issued = f"{spec.issued.day} de {MONTHS[spec.issued.month - 1]} de {spec.issued.year}"
    c.drawString(50, 690, f"Factura de venta # {spec.number.replace('-', ' ')}")
    c.drawString(50, 676, f"Fecha de expedición: {issued}")
    c.drawString(50, 662, f"Cliente: {BUYER[0]} / NIT {BUYER[1]}-{nit_check_digit(BUYER[1])}")
    y = draw_items(c, spec, 630, decimals=True) - 30
    c.setFont("Courier", 10)
    rate = int(spec.iva_rate * 100)
    for label, value in (
        ("Valor antes de IVA", sub),
        (f"IVA {rate}%", iva),
        ("Neto a pagar", total),
    ):
        c.drawString(300, y, f"{label:<20}{money(value, prefix='$'):>18}")
        y -= 14


def template_d(c: Canvas, spec: Spec, dv: int) -> None:
    sub, iva, total = amounts(spec)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(50, 740, "DOCUMENTO SOPORTE EN ADQUISICIONES")
    c.setFont("Helvetica", 10)
    c.drawString(50, 720, spec.supplier)
    c.drawString(50, 706, f"C.C./NIT {nit_text(spec.nit_base, dv)}")
    c.drawString(330, 720, f"Consecutivo {spec.number.replace('-', ' ')}")
    c.drawString(330, 706, f"Expedida el {spec.issued:%d.%m.%Y}")
    c.drawString(50, 680, f"Adquiriente: {BUYER[0]}")
    y = draw_items(c, spec, 650, decimals=False) - 30
    for label, value in (("Valor servicio", sub), ("IVA 19%", iva), ("Valor neto", total)):
        c.drawString(380, y, label)
        c.drawRightString(560, y, money(value, decimals=False))
        y -= 16


TEMPLATES = {"A": template_a, "B": template_b, "C": template_c, "D": template_d}


def generate(out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    truth = []
    for spec in SPECS:
        dv = nit_check_digit(spec.nit_base)
        printed_dv = (dv + 3) % 10 if spec.bad_dv else dv
        c = Canvas(str(out_dir / spec.file), pagesize=LETTER, invariant=True)
        c.setTitle(f"Factura {spec.number} (ficticia)")
        TEMPLATES[spec.template](c, spec, printed_dv)
        footer(c)
        c.save()
        sub, iva, total = amounts(spec)
        step = Decimal("1") if spec.template in "BD" else CENT  # B/D print whole pesos
        truth.append(
            {
                "file": spec.file,
                "template": spec.template,
                "fields": {
                    "invoice_number": spec.number,
                    "issue_date": spec.issued.isoformat(),
                    "supplier_name": spec.supplier,
                    "supplier_nit": f"{spec.nit_base}-{printed_dv}",
                    "subtotal": f"{sub:.2f}",
                    "iva": f"{iva.quantize(step):.2f}",
                    "total": f"{total.quantize(step):.2f}",
                },
                "expected_needs_review": bool(spec.expected_reasons),
                "expected_reasons": spec.expected_reasons,
            }
        )
    (out_dir / "ground_truth.json").write_text(json.dumps(truth, indent=2, ensure_ascii=False))
    return truth


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/samples")
    print(f"Generated {len(generate(target))} invoices in {target}/")
