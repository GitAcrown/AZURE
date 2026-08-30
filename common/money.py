"""Monnaie AZURE : stockée en bronze. 100 bronze = 1 argent, 100 argent = 1 or."""

from __future__ import annotations

from typing import Optional

from common import emojis as E
from common.asset_emojis import ui_emoji
from common.catalog.models import MoneySettings

_DEFAULT = MoneySettings()


def split_money(bronze: int, rates: Optional[MoneySettings] = None) -> tuple[int, int, int]:
    """(or, argent, bronze) à partir du total en bronze (jamais négatif)."""
    cfg = rates or _DEFAULT
    per_silver = cfg.bronze_per_silver
    per_gold = per_silver * cfg.silver_per_gold
    total = max(0, int(bronze))
    gold, rest = divmod(total, per_gold)
    silver, bronze_left = divmod(rest, per_silver)
    return gold, silver, bronze_left


def format_money(
    bronze: int,
    rates: Optional[MoneySettings] = None,
    *,
    compact: bool = True,
) -> str:
    """Affiche or / argent / bronze. Hors profil, les dénominations à 0 sont omises."""
    gold, silver, bronze_left = split_money(bronze, rates)
    gold_e = (ui_emoji("COIN3") or "").strip() or E.e(E.COIN3, "or")
    silver_e = (ui_emoji("COIN2") or "").strip() or E.e(E.COIN2, "arg.")
    bronze_e = (ui_emoji("COIN1") or "").strip() or E.e(E.COIN1, "br.")
    if not compact:
        return f"{gold_e} {gold}  {silver_e} {silver}  {bronze_e} {bronze_left}"
    parts: list[str] = []
    if gold:
        parts.append(f"{gold_e} {gold}")
    if silver:
        parts.append(f"{silver_e} {silver}")
    if bronze_left or not parts:
        parts.append(f"{bronze_e} {bronze_left}")
    return "  ".join(parts)


def format_money_plain(bronze: int, rates: Optional[MoneySettings] = None) -> str:
    """Prix pour descriptions de select (pas d'emoji custom)."""
    gold, silver, bronze_left = split_money(bronze, rates)
    parts: list[str] = []
    if gold:
        parts.append(f"{gold} or")
    if silver:
        parts.append(f"{silver} arg.")
    if bronze_left or not parts:
        parts.append(f"{bronze_left} br.")
    return " ".join(parts)
