from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from invoiceiq import config
from invoiceiq.db import Base


def test_schema_compiles_for_postgres():
    import invoiceiq.models  # noqa: F401

    ddl = [
        str(CreateTable(t).compile(dialect=postgresql.dialect()))
        for t in Base.metadata.sorted_tables
    ]
    assert any("BYTEA" in d for d in ddl) and any("JSON" in d for d in ddl)


def test_platform_database_url_is_normalized(monkeypatch):
    config.get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/db")
    try:
        assert config.get_settings().database_url == "postgresql+psycopg://u:p@host:5432/db"
    finally:
        config.get_settings.cache_clear()
