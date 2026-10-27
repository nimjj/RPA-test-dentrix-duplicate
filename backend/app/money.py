"""Money handling. Amounts live in the database as integer cents and travel over
the API as strings with exactly two decimals. Nothing is ever rounded: input
with more than two decimals is rejected."""
import re

_AMOUNT_RE = re.compile(r"^(\d{1,7})(?:\.(\d{1,2}))?$")


def parse_amount_to_cents(value: object) -> int:
    """Parse user input such as '125.40' into positive cents. Raises ValueError
    with a user-facing message."""
    if isinstance(value, bool) or value is None:
        raise ValueError("Amount is required.")
    text = str(value).strip()
    if text == "":
        raise ValueError("Amount is required.")
    if text.startswith("-"):
        raise ValueError("Amount must be greater than 0.")
    m = _AMOUNT_RE.match(text)
    if not m:
        raise ValueError("Amount must be a number with at most 2 decimal places, for example 125.40.")
    whole, frac = m.group(1), (m.group(2) or "")
    cents = int(whole) * 100 + int(frac.ljust(2, "0")) if frac else int(whole) * 100
    if cents <= 0:
        raise ValueError("Amount must be greater than 0.")
    return cents


def fmt_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}{c // 100}.{c % 100:02d}"
