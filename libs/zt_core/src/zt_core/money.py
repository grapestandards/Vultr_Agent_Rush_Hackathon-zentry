"""Money is integer satang everywhere. Convert only at the edges (input parsing, display)."""

from decimal import ROUND_HALF_UP, Decimal

SATANG_PER_BAHT = 100


def baht_to_satang(baht: str | int | Decimal) -> int:
    """Parse a baht amount ("1,234.50", 12, Decimal) into satang. Floats are rejected."""
    if isinstance(baht, float):
        raise TypeError("floats are not allowed for money; pass str or Decimal")
    value = Decimal(str(baht).replace(",", "").strip())
    return int((value * SATANG_PER_BAHT).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_thb(satang: int) -> str:
    """12345 -> '฿123.45'."""
    sign = "-" if satang < 0 else ""
    baht, rem = divmod(abs(satang), SATANG_PER_BAHT)
    return f"{sign}฿{baht:,}.{rem:02d}"
