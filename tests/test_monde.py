"""Carte /monde : coûts de lancer et notes de trajet."""

from __future__ import annotations

import asyncio
from pathlib import Path

from common.catalog import load_catalog
from common.player import open_store
from common.player.models import PlayerSnapshot
from cogs.azure.views import monde_cast_cost_bit, monde_presence_bit, monde_travel_note

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def test_monde_cast_cost_rain_and_clear() -> None:
    catalog = load_catalog(ASSETS)
    clear = monde_cast_cost_bit(catalog, "clear", ignore=False)
    assert "**8** énergie" in clear
    assert "+4" not in clear
    rain = monde_cast_cost_bit(catalog, "rain", ignore=False)
    assert "**12** énergie" in rain
    assert "+4" in rain
    wind = monde_cast_cost_bit(catalog, "wind", ignore=False)
    assert "énergie" in wind
    assert "+2" in wind
    ignored = monde_cast_cost_bit(catalog, "rain", ignore=True)
    assert "**8** énergie" in ignored
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


def test_monde_presence_bit() -> None:
    assert monde_presence_bit(0) == ""
    assert monde_presence_bit(1) == "**1 pêcheur**"
    assert monde_presence_bit(3) == "**3 pêcheurs**"


def test_milieu_presence_counts_players(tmp_path: Path) -> None:
    catalog = load_catalog(ASSETS)

    async def body() -> None:
        store = await open_store(tmp_path / "presence.db", catalog)
        try:
            await store.get_or_create(1, 1)
            await store.get_or_create(1, 2)
            await store.get_or_create(1, 3)
            await store.set_milieu(1, 1, "pond")
            await store.set_milieu(1, 2, "pond")
            await store.set_milieu(1, 3, "ocean")
            counts = await store.milieu_presence(1)
            assert counts["pond"] == 2
            assert counts["ocean"] == 1
            assert "river" not in counts
        finally:
            await store.close()

    asyncio.run(body())

