from datetime import date
from decimal import Decimal

import pytest

from invoiceiq.extraction.colombia import (
    format_cop,
    is_valid_nit,
    nit_check_digit,
    normalize_nit,
    parse_cop_amount,
    parse_date,
)


# Publicly listed NITs of large Colombian institutions, used only as check-digit vectors.
@pytest.mark.parametrize(
    ("base", "dv"),
    [("890903938", 8), ("899999068", 1), ("800197268", 4), ("860034313", 7), ("79123456", 0)],
)
def test_nit_check_digit_matches_dian_algorithm(base, dv):
    assert nit_check_digit(base) == dv


@pytest.mark.parametrize(
    ("raw", "valid"),
    [
        ("890.903.938-8", True),
        ("890903938-8", True),
        ("890 903 938 - 8", True),
        ("890.903.938-9", False),
        ("890903938", False),
        ("abc", False),
    ],
)
def test_is_valid_nit(raw, valid):
    assert is_valid_nit(raw) is valid


def test_normalize_nit():
    assert normalize_nit("1.020.304.050-1") == "1020304050-1"
    assert normalize_nit("900123456") is None


def test_nit_check_digit_rejects_garbage():
    with pytest.raises(ValueError):
        nit_check_digit("")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$ 1.250.000,50", "1250000.50"),
        ("COP 1.487.500", "1487500.00"),
        ("$237.500", "237500.00"),
        ("1,250,000.50", "1250000.50"),
        ("950,5", "950.50"),
        ("1250000", "1250000.00"),
        ("$ 18.500,00", "18500.00"),
    ],
)
def test_parse_cop_amount(raw, expected):
    assert parse_cop_amount(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["", "abc", "$", "12a"])
def test_parse_cop_amount_invalid(raw):
    assert parse_cop_amount(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("15/03/2026", date(2026, 3, 15)),
        ("2026-03-15", date(2026, 3, 15)),
        ("2 de abril de 2026", date(2026, 4, 2)),
        ("31/02/2026", None),
        ("2 de abrul de 2026", None),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_format_cop():
    assert format_cop(Decimal("1487500.5")) == "$ 1.487.500,50"
