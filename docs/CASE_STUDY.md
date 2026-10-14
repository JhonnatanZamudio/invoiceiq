# Case study: InvoiceIQ (portfolio demo, not a client project)

**Problem.** Small companies in Colombia and LatAm receive supplier invoices as PDFs, and
someone retypes the number, date, supplier, NIT, subtotal, IVA and total into Excel. It is
slow and error-prone.

**Approach.** Rules come first because Colombian invoices follow regulated conventions: the
DIAN NIT check digit, `dd/mm/yyyy` dates and amounts like `1.234.567,89`. Each field gets a
confidence score. Only weak fields go to a pluggable LLM provider, and its answer is checked
with Pydantic and kept below the review threshold. Validation rules (NIT, totals, IVA rate,
future dates, duplicates) either auto-approve an invoice or send it to a human review queue
with the reasons shown.

**Architecture.** FastAPI and SQLAlchemy 2.0 with tenant-scoped queries. JWT/bcrypt auth
with roles. Vanilla-JS SPA in Spanish. XLSX/CSV export. Postgres-ready, with Docker, Render,
Fly and CI configs.

**Result.** Measured on 13 synthetic invoices with an offline FakeProvider:

- 94.5% field accuracy.
- 12/13 invoices fully extracted by rules alone.
- 13/13 invoices correctly routed to review or approval.
- About 25 ms per invoice.
- 61 tests.

The rules were written against these templates, so this is not a real-world accuracy
figure.

**What I'd do in production:**

- Ingest the DIAN UBL XML first and use the PDF as the fallback.
- Add OCR for scanned PDFs.
- Use a job queue.
- Store originals in S3.
- Use Alembic migrations.
- Add audit logs.
- Measure accuracy on a labelled set of real invoices.
