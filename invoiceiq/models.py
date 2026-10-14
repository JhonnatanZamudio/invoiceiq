import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Index, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from invoiceiq.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Role(enum.StrEnum):
    owner = "owner"
    member = "member"


class InvoiceStatus(enum.StrEnum):
    processing = "processing"
    needs_review = "needs_review"
    approved = "approved"


class FieldSource(enum.StrEnum):
    rules = "rules"
    llm = "llm"
    human = "human"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    users: Mapped[list["User"]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), default=Role.member)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    organization: Mapped[Organization] = relationship(back_populates="users")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        # Duplicate detection: same supplier + number inside one tenant.
        Index("ix_invoice_dedupe", "organization_id", "supplier_nit", "invoice_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    uploaded_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, native_enum=False), default=InvoiceStatus.processing, index=True
    )
    # Denormalised copies of key fields for indexing/dedupe; source of truth is `fields`.
    supplier_nit: Mapped[str | None] = mapped_column(String(20))
    invoice_number: Mapped[str | None] = mapped_column(String(50))
    review_reasons: Mapped[list[dict]] = mapped_column(JSON, default=list)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    processing_ms: Mapped[float | None] = mapped_column(Float)
    approved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id])
    fields: Mapped[list["ExtractionField"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="ExtractionField.position"
    )

    file: Mapped["InvoiceFile"] = relationship(cascade="all, delete-orphan", lazy="select")

    def field_map(self) -> dict[str, "ExtractionField"]:
        return {f.name: f for f in self.fields}


class InvoiceFile(Base):
    """Original PDF, kept out of the invoices table so list queries stay light.

    Stored in the database so the demo deploys statelessly (Render/Fly + Postgres only);
    in production this would be object storage (S3/GCS) with presigned URLs.
    """

    __tablename__ = "invoice_files"

    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), primary_key=True
    )
    content: Mapped[bytes] = mapped_column(LargeBinary)


class ExtractionField(Base):
    __tablename__ = "extraction_fields"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(50))
    position: Mapped[int] = mapped_column(default=0)
    value: Mapped[str | None] = mapped_column(String(500))  # normalised string form
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[FieldSource] = mapped_column(Enum(FieldSource, native_enum=False))

    invoice: Mapped[Invoice] = relationship(back_populates="fields")
