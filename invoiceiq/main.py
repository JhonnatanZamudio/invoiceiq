from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from invoiceiq import __version__
from invoiceiq.api import auth, invoices
from invoiceiq.config import Settings, get_settings
from invoiceiq.db import init_db, make_engine
from invoiceiq.extraction.llm import LLMProvider, build_provider

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None, provider: LLMProvider | None = None) -> FastAPI:
    """App factory. Run with: uvicorn invoiceiq.main:create_app --factory"""
    settings = settings or get_settings()
    if settings.secret_key == Settings.model_fields["secret_key"].default and not (
        settings.database_url.startswith("sqlite")
    ):
        raise RuntimeError("Set INVOICEIQ_SECRET_KEY before running against a real database")
    app = FastAPI(
        title="InvoiceIQ",
        version=__version__,
        description="Supplier invoice PDFs → validated, structured data.",
    )
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = init_db(app.state.engine)
    app.state.llm_provider = provider or build_provider(settings)

    app.include_router(auth.router)
    app.include_router(invoices.router)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        return {"status": "ok", "version": __version__, "llm": app.state.llm_provider.name}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
