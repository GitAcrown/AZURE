"""Tests de la monnaie bronze / argent / or."""

from __future__ import annotations

from common.money import format_money, split_money


def test_split_money_thresholds() -> None:
    assert split_money(0) == (0, 0, 0)
    assert split_money(99) == (0, 0, 99)
    assert split_money(100) == (0, 1, 0)
    assert split_money(101) == (0, 1, 1)
    assert split_money(10000) == (1, 0, 0)
    assert split_money(12345) == (1, 23, 45)


def test_format_money_fallback_labels() -> None:
    text = format_money(12345)
    assert "1" in text
    assert "23" in text
    assert "45" in text


def test_format_money_compact_skips_zero_denominations() -> None:
    only_bronze = format_money(12)
    assert "12" in only_bronze
    assert "or" not in only_bronze
    assert "arg." not in only_bronze

    only_gold = format_money(10000)
    assert "1" in only_gold
    assert "arg." not in only_gold
    assert "br." not in only_gold

    zero = format_money(0)
    assert "0" in zero


def test_format_money_profile_keeps_zeros() -> None:
    text = format_money(12, compact=False)
    assert "or" in text
    assert "arg." in text
    assert "br." in text
    assert "0" in text

