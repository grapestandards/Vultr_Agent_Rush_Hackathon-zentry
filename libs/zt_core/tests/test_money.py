import pytest

from zt_core.money import baht_to_satang, format_thb


def test_round_trip():
    assert baht_to_satang("1,234.50") == 123450
    assert format_thb(123450) == "฿1,234.50"
    assert format_thb(-5) == "-฿0.05"


def test_rejects_float():
    with pytest.raises(TypeError):
        baht_to_satang(1.1)
