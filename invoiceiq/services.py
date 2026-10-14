"""Invoice use cases. Every function takes the acting user and scopes by their organization."""

import csv
import io
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException, status
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from invoiceiq.config import Settings
from invoiceiq.extraction.colombia import normalize_nit, parse_cop_amount, parse_date
from invoiceiq.extraction.llm import LLMProvider
from invoiceiq.extraction.pipeline import run_pipeline
from invoiceiq.extraction.types import AMOUNT_FIELDS, FIELD_NAMES, FieldResult, Issue
from invoiceiq.extraction.validation import FIELD_LABELS, validate
from invoiceiq.models import (
    ExtractionField,
    FieldSource,
    Invoice,
    InvoiceFile,
    InvoiceStatus,
    Role,
    User,
)


def scoped_invoices(user: User) -> Select[tuple[Invoice]]:
    """The only entry point for invoice queries: tenant isolation lives here."""
    return (
        select(Invoice)
        .where(Invoice.organization_id == user.organization_id)
        .options(selectinload(Invoice.fields))
    )


def get_invoice(db: Session, user: User, invoice_id: str) -> Invoice:
    invoice = db.scalar(scoped_invoices(user).where(Invoice.id == invoice_id))
    if invoice is None:  # 404 (not 403) so other tenants' IDs are not even confirmed to exist
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return invoice


def list_invoices(db: Session, user: User, status_: InvoiceStatus | None) -> list[Invoice]:
    stmt = scoped_invoices(user).order_by(Invoice.created_at.desc())
    if status_:
        stmt = stmt.where(Invoice.status == status_)
    return list(db.scalars(stmt))


def _duplicate_checker(db: Session, org_id: str, exclude_id: str | None):
    def is_duplicate(nit: str, number: str) -> bool:
        stmt = select(Invoice.id).where(
            Invoice.organization_id == org_id,
            Invoice.supplier_nit == nit,
            Invoice.invoice_number == number,
        )
        if exclude_id:
            stmt = stmt.where(Invoice.id != exclude_id)
        return db.scalar(stmt.limit(1)) is not None

    return is_duplicate


def _store_fields(invoice: Invoice, fields: dict[str, FieldResult]) -> None:
    existing = invoice.field_map()
    for pos, name in enumerate(FIELD_NAMES):
        result = fields[name]
        row = existing.get(name) or ExtractionField(name=name, position=pos)
        row.value, row.confidence, row.source = result.value, result.confidence, result.source
        if name not in existing:
            invoice.fields.append(row)
    invoice.supplier_nit = fields["supplier_nit"].value
    invoice.invoice_number = fields["invoice_number"].value


def _field_results(invoice: Invoice) -> dict[str, FieldResult]:
    return {f.name: FieldResult(f.value, f.confidence, f.source.value) for f in invoice.fields}


def process_upload(
    db: Session,
    user: User,
    filename: str,
    data: bytes,
    settings: Settings,
    provider: LLMProvider,
    today: date | None = None,
) -> Invoice:
    if not data.startswith(b"%PDF"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF files are accepted")
    invoice = Invoice(
        organization_id=user.organization_id,
        uploaded_by_id=user.id,
        filename=Path(filename).name[:255],
        file=InvoiceFile(content=data),
    )
    db.add(invoice)
    db.flush()  # assigns id; status=processing until the pipeline finishes
    result = run_pipeline(
        data,
        provider=provider,
        is_duplicate=_duplicate_checker(db, user.organization_id, invoice.id),
        today=today or date.today(),
        review_threshold=settings.review_threshold,
        llm_confidence_cap=settings.llm_confidence_cap,
        tolerance=Decimal(str(settings.totals_tolerance_cop)),
    )
    _store_fields(invoice, result.fields)
    invoice.raw_text = result.text
    invoice.processing_ms = round(result.elapsed_ms, 1)
    invoice.review_reasons = [i.as_dict() for i in result.issues]
    if result.issues or not settings.auto_approve_clean:
        invoice.status = InvoiceStatus.needs_review
    else:
        invoice.status = InvoiceStatus.approved
        invoice.approved_at = datetime.now(UTC)
    db.commit()
    return invoice


def _normalize(name: str, raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    raw = raw.strip()
    if name in AMOUNT_FIELDS:
        value = parse_cop_amount(raw)
        normalized = f"{value:.2f}" if value is not None else None
    elif name == "issue_date":
        parsed = parse_date(raw)
        normalized = parsed.isoformat() if parsed else None
    elif name == "supplier_nit":
        normalized = normalize_nit(raw)
    else:
        normalized = raw[:200]
    if normalized is None:
        raise HTTPException(422, f"Invalid value for {FIELD_LABELS.get(name, name)}: {raw!r}")
    return normalized


def revalidate(db: Session, invoice: Invoice, settings: Settings, today: date) -> list[Issue]:
    issues = validate(
        _field_results(invoice),
        today=today,
        is_duplicate=_duplicate_checker(db, invoice.organization_id, invoice.id),
        review_threshold=settings.review_threshold,
        tolerance=Decimal(str(settings.totals_tolerance_cop)),
    )
    invoice.review_reasons = [i.as_dict() for i in issues]
    return issues


def update_fields(
    db: Session, invoice: Invoice, updates: dict[str, str | None], settings: Settings
) -> Invoice:
    unknown = set(updates) - set(FIELD_NAMES)
    if unknown:
        raise HTTPException(422, f"Unknown fields: {sorted(unknown)}")
    if invoice.status == InvoiceStatus.approved:
        raise HTTPException(status.HTTP_409_CONFLICT, "Approved invoices are read-only")
    rows = invoice.field_map()
    for name, raw in updates.items():
        row = rows[name]
        row.value, row.confidence, row.source = _normalize(name, raw), 1.0, FieldSource.human
    invoice.supplier_nit = rows["supplier_nit"].value
    invoice.invoice_number = rows["invoice_number"].value
    revalidate(db, invoice, settings, date.today())
    invoice.status = InvoiceStatus.needs_review
    db.commit()
    return invoice


def approve(db: Session, user: User, invoice: Invoice, settings: Settings, force: bool) -> Invoice:
    if invoice.status == InvoiceStatus.approved:
        return invoice
    issues = revalidate(db, invoice, settings, date.today())
    errors = [i for i in issues if i.severity == "error"]
    if errors and not (force and user.role == Role.owner):
        db.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": "Validation errors must be fixed (owners may force-approve)",
                "issues": [e.as_dict() for e in errors],
            },
        )
    invoice.status = InvoiceStatus.approved
    invoice.approved_by_id = user.id
    invoice.approved_at = datetime.now(UTC)
    db.commit()
    return invoice


EXPORT_COLUMNS = [
    "invoice_number",
    "issue_date",
    "supplier_name",
    "supplier_nit",
    "subtotal",
    "iva",
    "total",
]
EXPORT_HEADERS = [
    "Número",
    "Fecha",
    "Proveedor",
    "NIT",
    "Subtotal",
    "IVA",
    "Total",
    "Archivo",
    "Aprobada",
]


def export_rows(db: Session, user: User) -> list[list]:
    rows = []
    for inv in list_invoices(db, user, InvoiceStatus.approved):
        f = inv.field_map()
        values: list = [f[c].value if c in f else None for c in EXPORT_COLUMNS]
        for i, col in enumerate(EXPORT_COLUMNS):
            if col in AMOUNT_FIELDS and values[i] is not None:
                values[i] = Decimal(values[i])
        approved = inv.approved_at.strftime("%Y-%m-%d %H:%M") if inv.approved_at else ""
        rows.append([*values, inv.filename, approved])
    return rows


def to_csv(rows: list[list]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_HEADERS)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens accents correctly


def to_xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Facturas aprobadas"
    ws.append(EXPORT_HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0F3D5E")
    for row in rows:
        ws.append([float(v) if isinstance(v, Decimal) else v for v in row])
    for col in "EFG":
        for cell in ws[col][1:]:
            cell.number_format = "#,##0.00"
    for col, width in zip("ABCDEFGHI", (14, 12, 36, 16, 16, 14, 16, 28, 18), strict=True):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
