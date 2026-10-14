from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from invoiceiq import services
from invoiceiq.config import Settings
from invoiceiq.db import get_db
from invoiceiq.deps import current_user, get_provider, get_settings
from invoiceiq.extraction.llm import LLMProvider
from invoiceiq.extraction.validation import FIELD_LABELS
from invoiceiq.models import Invoice, InvoiceStatus, User
from invoiceiq.schemas import (
    ApproveIn,
    FieldOut,
    FieldsUpdate,
    InvoiceDetail,
    InvoiceSummary,
    IssueOut,
)

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


def _summary_kwargs(inv: Invoice) -> dict:
    f = inv.field_map()
    val = lambda name: f[name].value if name in f else None  # noqa: E731
    return dict(
        id=inv.id,
        filename=inv.filename,
        status=inv.status,
        invoice_number=val("invoice_number"),
        supplier_name=val("supplier_name"),
        supplier_nit=val("supplier_nit"),
        issue_date=val("issue_date"),
        total=val("total"),
        issue_count=len(inv.review_reasons or []),
        created_at=inv.created_at,
    )


def to_detail(inv: Invoice) -> InvoiceDetail:
    return InvoiceDetail(
        **_summary_kwargs(inv),
        fields=[
            FieldOut(
                name=f.name,
                label=FIELD_LABELS[f.name],
                value=f.value,
                confidence=f.confidence,
                source=f.source,
            )
            for f in inv.fields
        ],
        review_reasons=[IssueOut(**r) for r in inv.review_reasons or []],
        raw_text=inv.raw_text,
        processing_ms=inv.processing_ms,
        approved_at=inv.approved_at,
        approved_by=inv.approved_by.email
        if inv.approved_by
        else ("auto (sin alertas)" if inv.approved_at else None),
    )


@router.post("", response_model=InvoiceDetail, status_code=201)
async def upload_invoice(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    provider: LLMProvider = Depends(get_provider),
) -> InvoiceDetail:
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File larger than {settings.max_upload_mb} MB")
    invoice = services.process_upload(
        db, user, file.filename or "factura.pdf", data, settings, provider
    )
    return to_detail(invoice)


@router.get("", response_model=list[InvoiceSummary])
def list_invoices(
    status: InvoiceStatus | None = Query(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[InvoiceSummary]:
    return [InvoiceSummary(**_summary_kwargs(i)) for i in services.list_invoices(db, user, status)]


@router.get("/export")
def export_invoices(
    format: Literal["xlsx", "csv"] = "xlsx",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    rows = services.export_rows(db, user)
    stamp = date.today().isoformat()
    if format == "csv":
        content, media = services.to_csv(rows), "text/csv; charset=utf-8"
    else:
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        content = services.to_xlsx(rows)
    headers = {"Content-Disposition": f'attachment; filename="facturas-{stamp}.{format}"'}
    return Response(content, media_type=media, headers=headers)


@router.get("/{invoice_id}", response_model=InvoiceDetail)
def get_invoice(
    invoice_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> InvoiceDetail:
    return to_detail(services.get_invoice(db, user, invoice_id))


@router.get("/{invoice_id}/file")
def download_original(
    invoice_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    invoice = services.get_invoice(db, user, invoice_id)
    headers = {"Content-Disposition": f'inline; filename="{invoice.id}.pdf"'}
    return Response(invoice.file.content, media_type="application/pdf", headers=headers)


@router.patch("/{invoice_id}/fields", response_model=InvoiceDetail)
def edit_fields(
    invoice_id: str,
    body: FieldsUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> InvoiceDetail:
    invoice = services.get_invoice(db, user, invoice_id)
    return to_detail(services.update_fields(db, invoice, body.fields, settings))


@router.post("/{invoice_id}/approve", response_model=InvoiceDetail)
def approve_invoice(
    invoice_id: str,
    body: ApproveIn | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> InvoiceDetail:
    invoice = services.get_invoice(db, user, invoice_id)
    force = body.force if body else False
    return to_detail(services.approve(db, user, invoice, settings, force))
