import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from invoiceiq.models import FieldSource, InvoiceStatus, Role

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class _Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("invalid email")
        return v


class SignupIn(_Credentials):
    organization_name: str = Field(min_length=2, max_length=200)


class LoginIn(_Credentials):
    password: str = Field(min_length=1, max_length=128)


class MemberIn(_Credentials):
    role: Role = Role.member


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    role: Role
    organization_id: str
    organization_name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class FieldOut(BaseModel):
    name: str
    label: str
    value: str | None
    confidence: float
    source: FieldSource


class IssueOut(BaseModel):
    code: str
    message: str
    field: str | None = None
    severity: str = "error"


class InvoiceSummary(BaseModel):
    id: str
    filename: str
    status: InvoiceStatus
    invoice_number: str | None
    supplier_name: str | None
    supplier_nit: str | None
    issue_date: str | None
    total: str | None
    issue_count: int
    created_at: datetime


class InvoiceDetail(InvoiceSummary):
    fields: list[FieldOut]
    review_reasons: list[IssueOut]
    raw_text: str
    processing_ms: float | None
    approved_at: datetime | None
    approved_by: str | None


class FieldsUpdate(BaseModel):
    fields: dict[str, str | None] = Field(min_length=1)


class ApproveIn(BaseModel):
    force: bool = False  # owners may approve despite validation errors
