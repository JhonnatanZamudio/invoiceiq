import pytest

from invoiceiq.extraction.pipeline import pdf_to_text
from invoiceiq.extraction.rules import extract_issue_date, extract_with_rules
from invoiceiq.extraction.types import FIELD_NAMES


def _rules(samples, item):
    return extract_with_rules(pdf_to_text((samples / item["file"]).read_bytes()))


def test_rules_extract_every_field_on_known_templates(samples, ground_truth):
    known = [g for g in ground_truth if g["template"] in "ABC"]
    assert len(known) >= 12
    for item in known:
        got = _rules(samples, item)
        for name in FIELD_NAMES:
            expected = item["fields"][name]
            value = got[name].value or ""
            if name == "supplier_name":
                value, expected = value.casefold(), expected.casefold()
            assert value == expected, f"{item['file']}:{name}"
            assert got[name].confidence >= 0.8


def test_supplier_nit_is_issuer_not_client(samples, ground_truth):
    for item in ground_truth:
        assert _rules(samples, item)["supplier_nit"].value != "901234567-7"  # buyer's NIT


def test_due_date_is_not_taken_as_issue_date():
    text = "Fecha de vencimiento: 30/04/2026\nFecha de emisión: 01/04/2026"
    assert extract_issue_date(text).value == "2026-04-01"


@pytest.mark.parametrize("template", ["D"])
def test_unknown_layout_yields_missing_fields_not_guesses(samples, ground_truth, template):
    item = next(g for g in ground_truth if g["template"] == template)
    got = _rules(samples, item)
    assert got["invoice_number"].value is None
    assert got["issue_date"].value is None
