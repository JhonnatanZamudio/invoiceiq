FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN useradd --create-home --uid 10001 app

# Dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY invoiceiq ./invoiceiq
RUN pip install ".[postgres]"

COPY data/samples ./data/samples

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz')"

# PORT is injected by Render/Fly; defaults to 8000 locally.
CMD ["sh", "-c", "uvicorn invoiceiq.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
