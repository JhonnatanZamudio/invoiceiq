PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: demo install samples seed run test lint bench screenshots up clean

demo: install samples seed run  ## One command: install, generate samples, seed, serve

install:            ## Create venv and install app + dev tools
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -e ".[dev]"

samples:            ## Generate fictional invoice PDFs + ground truth into data/samples/
	$(BIN)/python scripts/make_invoices.py

seed:               ## Create the local demo org/user and upload the sample invoices
	$(BIN)/python -m invoiceiq.seed --with-samples

run:                ## Start the API + UI on http://localhost:8000
	$(BIN)/uvicorn invoiceiq.main:create_app --factory --reload --port 8000

test:               ## Lint + tests
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	$(BIN)/pytest

lint:
	$(BIN)/ruff check . && $(BIN)/ruff format --check .

bench:              ## Run extraction benchmark -> bench/results.json
	$(BIN)/python -m invoiceiq.bench

screenshots:        ## Capture UI screenshots (server must be running and seeded)
	$(BIN)/python scripts/screenshots.py

up:                 ## Postgres + app via docker compose
	docker compose up --build

clean:
	rm -rf invoiceiq.db .pytest_cache .ruff_cache
