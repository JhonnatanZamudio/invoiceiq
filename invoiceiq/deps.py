from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError
from sqlalchemy.orm import Session

from invoiceiq.config import Settings
from invoiceiq.db import get_db
from invoiceiq.extraction.llm import LLMProvider
from invoiceiq.models import Role, User
from invoiceiq.security import decode_access_token

bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.llm_provider


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", {"WWW-Authenticate": "Bearer"}
    )
    if creds is None:
        raise unauthorized
    try:
        claims = decode_access_token(creds.credentials, settings.secret_key)
    except PyJWTError:
        raise unauthorized from None
    user = db.get(User, claims["sub"])
    # The org claim must still match: a user moved between orgs invalidates old tokens.
    if user is None or user.organization_id != claims.get("org"):
        raise unauthorized
    return user


def require_owner(user: User = Depends(current_user)) -> User:
    if user.role != Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner role required")
    return user
