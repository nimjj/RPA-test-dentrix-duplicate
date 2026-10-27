import pytest

from app.money import fmt_cents, parse_amount_to_cents


def test_125_40_stays_125_40():
    assert parse_amount_to_cents("125.40") == 12540
    assert fmt_cents(12540) == "125.40"


@pytest.mark.parametrize(
    "text,cents",
    [("125.4", 12540), ("125", 12500), ("0.01", 1), ("1000000.00", 100000000), (" 7.05 ", 705), ("0.10", 10)],
)
def test_valid_amounts(text, cents):
    assert parse_amount_to_cents(text) == cents


@pytest.mark.parametrize("text", ["0", "0.00", "-5", "-0.01", "125.405", "12.999", "abc", "", "1e3", "$5", "1,000.00", "12.", ".5"])
def test_invalid_amounts_are_rejected_not_rounded(text):
    with pytest.raises(ValueError):
        parse_amount_to_cents(text)


def test_float_input_uses_its_text_form():
    assert parse_amount_to_cents(125.4) == 12540


def test_fmt_negative_and_small():
    assert fmt_cents(-12540) == "-125.40"
    assert fmt_cents(5) == "0.05"
    assert fmt_cents(0) == "0.00"
