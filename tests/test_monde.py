"""Carte /monde : coûts de lancer et notes de trajet."""

from __future__ import annotations

from pathlib import Path

from common.catalog import load_catalog
from common.player.models import PlayerSnapshot
from cogs.azure.views import monde_cast_cost_bit, monde_travel_note

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def test_monde_cast_cost_rain_and_clear() -> None:
    catalog = load_catalog(ASSETS)
    clear = monde_cast_cost_bit(catalog, "clear", ignore=False)
    assert "**8**" in clear
    assert "+4" not in clear
    rain = monde_cast_cost_bit(catalog, "rain", ignore=False)
    assert "**12**" in rain
    assert "+4" in rain
    wind = monde_cast_cost_bit(catalog, "wind", ignore=False)
    assert "+2" in wind
    ignored = monde_cast_cost_bit(catalog, "rain", ignore=True)
    assert "**8**" in ignored
    assert "+4" not in ignored


def test_monde_travel_note_first_then_walk() -> None:
    catalog = load_catalog(ASSETS)
    empty = PlayerSnapshot(
        guild_id=1,
        user_id=1,
        energy=100,
        energy_max=100,
        energy_max_base=100,
        money=0,
        milieu_key=None,
        created_at="",
    )
    first = monde_travel_note(catalog, empty)
    assert "immédiat" in first
    assert "/village" in first
    there = PlayerSnapshot(
        guild_id=1,
        user_id=1,
        energy=100,
        energy_max=100,
        energy_max_base=100,
        money=0,
        milieu_key="pond",
        created_at="",
    )
    later = monde_travel_note(catalog, there)
    assert "gratuite" in later
    assert "immédiat" not in later
    assert "/village" in later
