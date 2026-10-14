"""Create a local demo tenant: python -m invoiceiq.seed [--with-samples]

The credentials below are for LOCAL development only and are documented in the README.
"""

import argparse
from pathlib import Path

from sqlalchemy import select

from invoiceiq import services
from invoiceiq.config import get_settings
from invoiceiq.db import init_db, make_engine
from invoiceiq.extraction.llm import build_provider
from invoiceiq.models import Invoice, Organization, Role, User
from invoiceiq.security import hash_password

DEMO_EMAIL = "demo@invoiceiq.local"
DEMO_PASSWORD = "demo-invoiceiq-2026"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-samples", action="store_true", help="also upload sample PDFs")
    parser.add_argument("--samples", type=Path, default=Path("data/samples"))
    args = parser.parse_args()

    settings = get_settings()
    session = init_db(make_engine(settings.database_url))()
    user = session.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        org = Organization(name="Empresa Demo S.A.S.")
        user = User(
            organization=org,
            email=DEMO_EMAIL,
            role=Role.owner,
            password_hash=hash_password(DEMO_PASSWORD),
        )
        session.add_all([org, user])
        session.commit()
        print(f"Created demo org + user {DEMO_EMAIL}")
    else:
        print(f"Demo user {DEMO_EMAIL} already exists")

    has_invoices = session.scalar(
        select(Invoice.id).where(Invoice.organization_id == user.organization_id).limit(1)
    )
    if args.with_samples and has_invoices:
        print("Demo org already has invoices; skipping sample upload")
    elif args.with_samples:
        provider = build_provider(settings)
        for pdf in sorted(args.samples.glob("*.pdf")):
            inv = services.process_upload(
                session, user, pdf.name, pdf.read_bytes(), settings, provider
            )
            print(f"  {pdf.name:<26} -> {inv.status.value}")
    session.close()


if __name__ == "__main__":
    main()
