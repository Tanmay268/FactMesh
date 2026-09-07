from app.normalize.numbers import parse_number


def test_plain_number():
    assert parse_number("18,540") == 18540.0


def test_decimal():
    assert parse_number("81,415.38") == 81415.38


def test_parenthesized_negative():
    assert parse_number("(452.3)") == -452.3


def test_currency_parenthesized_negative():
    assert parse_number("₹(452) Cr") == -452.0


def test_leading_minus():
    assert parse_number("-1,227.49") == -1227.49


def test_percent_sign_ignored():
    assert parse_number("18.15%") == 18.15


def test_dash_is_none():
    assert parse_number("-") is None
    assert parse_number("–") is None


def test_na_is_none():
    assert parse_number("N/A") is None


def test_empty_is_none():
    assert parse_number("") is None
    assert parse_number(None) is None


def test_zero_stays_zero_not_negative_zero():
    assert parse_number("(0)") == 0.0
