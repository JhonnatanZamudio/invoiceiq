from datetime import date

from invoiceiq.extraction.types import FieldResult
from invoiceiq.extraction.validation import validate

TODAY = date(2026, 6, 1)
CLEAN = {
    "invoice_number": "FE-1",
    "issue_date": "2026-03-15",
    "supplier_name": "Proveedor Demo",
    "supplier_nit": "890903938-8",
    "subtotal": "1000000.00",
    "iva": "190000.00",
    "total": "1190000.00",
}


def run(overrides=None, conf=0.95, duplicate=False, source="rules"):
    values = {**CLEAN, **(overrides or {})}
    fields = {k: FieldResult(v, conf, source) for k, v in values.items()}
    return {
        i.code
        for i in validate(
            fields, today=TODAY, is_duplicate=lambda *_: duplicate, review_threshold=0.8
        )
    }


def test_clean_invoice_has_no_issues():
    assert run() == set()


def test_totals_mismatch_and_tolerance():
    assert run({"total": "1190001.00"}) == set()  # within 1 COP rounding tolerance
    assert run({"total": "1205000.00"}) == {"totals_mismatch"}


def test_invalid_nit_check_digit():
    assert run({"supplier_nit": "890903938-1"}) == {"nit_invalid"}


def test_future_date():
    assert run({"issue_date": "2026-06-02"}) == {"date_future"}


def test_duplicate_invoice_number_per_supplier():
    assert run(duplicate=True) == {"duplicate"}


def test_unusual_iva_rate_is_a_warning():
    assert run({"iva": "100000.00", "total": "1100000.00"}) == {"iva_rate"}
    assert run({"iva": "50000.00", "total": "1050000.00"}) == set()  # 5% is a legal rate


def test_missing_and_low_confidence_fields():
    assert "missing_field" in run({"total": None})
    assert run(conf=0.5) == {"low_confidence"}
    assert run(conf=0.5, source="human") == set()  # human-entered values are trusted
