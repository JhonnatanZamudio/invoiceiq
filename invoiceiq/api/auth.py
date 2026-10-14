from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from invoiceiq.config import Settings
from invoiceiq.db import get_db
from invoiceiq.deps import current_user, get_settings, require_owner
from invoiceiq.models import Organization, Role, User
from invoiceiq.schemas import LoginIn, MemberIn, SignupIn, TokenOut, UserOut
from invoiceiq.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api", tags=["auth"])


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        organization_id=user.organization_id,
        organization_name=user.organization.name,
    )


def _token(user: User, settings: Settings) -> TokenOut:
    token = create_access_token(
        user.id, user.organization_id, settings.secret_key, settings.access_token_minutes
    )
    return TokenOut(access_token=token, user=user_out(user))


def _ensure_email_free(db: Session, email: str) -> None:
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")


@router.post("/auth/signup", response_model=TokenOut, status_code=201)
def signup(
    body: SignupIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> TokenOut:
    """Creates a new organization (tenant) and its first user as owner."""
    _ensure_email_free(db, body.email)
    org = Organization(name=body.organization_name.strip())
    user = User(
        organization=org,
        email=body.email,
        role=Role.owner,
        password_hash=hash_password(body.password),
    )
    db.add_all([org, user])
    db.commit()
    return _token(user, settings)


@router.post("/auth/login", response_model=TokenOut)
def login(
    body: LoginIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> TokenOut:
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return _token(user, settings)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return user_out(user)


@router.post("/users", response_model=UserOut, status_code=201)
def add_member(
    body: MemberIn, owner: User = Depends(require_owner), db: Session = Depends(get_db)
) -> UserOut:
    """Owners invite teammates into their own organization only."""
    _ensure_email_free(db, body.email)
    user = User(
        organization_id=owner.organization_id,
        email=body.email,
        role=body.role,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_out(user)
