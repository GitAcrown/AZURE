"""Tests de l'horloge et de la météo déterministe."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from common.catalog import load_catalog
from common.world import (
    season_at,
    time_of_day_at,
    weather_at,
    world_state,
)

ROOT = Path(__file__).resolve().parents[1]
PARIS = ZoneInfo("Europe/Paris")


def _world():
    return load_catalog(ROOT / "assets").game.world


def _at(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=PARIS)


def test_seasons_northern_hemisphere() -> None:
    world = _world()
    assert season_at(_at(2026, 3, 21, 12), world) == "spring"
    assert season_at(_at(2026, 6, 21, 12), world) == "summer"
    assert season_at(_at(2026, 9, 21, 12), world) == "autumn"
    assert season_at(_at(2026, 12, 21, 12), world) == "winter"
    assert season_at(_at(2026, 1, 15, 12), world) == "winter"


def test_time_windows() -> None:
    world = _world()
    assert time_of_day_at(_at(2026, 8, 30, 5), world) == "dawn"
    assert time_of_day_at(_at(2026, 8, 30, 7, 59), world) == "dawn"
    assert time_of_day_at(_at(2026, 8, 30, 8), world) == "day"
    assert time_of_day_at(_at(2026, 8, 30, 12), world) == "day"
    assert time_of_day_at(_at(2026, 8, 30, 18), world) == "dusk"
    assert time_of_day_at(_at(2026, 8, 30, 21), world) == "night"
    assert time_of_day_at(_at(2026, 8, 30, 23), world) == "night"
    assert time_of_day_at(_at(2026, 8, 30, 2), world) == "night"


def test_weather_is_deterministic() -> None:
    world = _world()
    dt = _at(2026, 8, 30, 18, 30)
    a = weather_at(111, "ocean", dt, world)
    b = weather_at(111, "ocean", dt, world)
    assert a.key == b.key
    later_same_bucket = _at(2026, 8, 30, 18, 59)
    assert weather_at(111, "ocean", later_same_bucket, world).key == a.key


def test_weather_differs_by_guild_and_milieu() -> None:
    world = _world()
    dt = _at(2026, 8, 30, 12)
    ocean_a = weather_at(1, "ocean", dt, world)
    ocean_b = weather_at(2, "ocean", dt, world)
    river_a = weather_at(1, "river", dt, world)
    assert ocean_a.key == weather_at(1, "ocean", dt, world).key
    differed = ocean_a.key != ocean_b.key or ocean_a.key != river_a.key
    if not differed:
        for hour in range(24):
            t = _at(2026, 8, 30, hour)
            if weather_at(1, "ocean", t, world).key != weather_at(1, "river", t, world).key:
                differed = True
                break
    assert differed


def test_world_state_fills_all_milieus() -> None:
    catalog = load_catalog(ROOT / "assets")
    state = world_state(
        catalog.game.world,
        42,
        [m.key for m in catalog.milieus],
        at=_at(2026, 4, 10, 6, 15),
    )
    assert state.season == "spring"
    assert state.time_of_day == "dawn"
    assert set(state.weathers) == {"ocean", "river", "pond"}
    assert state.next_bucket_at > state.at
    assert catalog.game.world.timezone == "Europe/Paris"
    assert catalog.game.world.weather_bucket_minutes == 60
    assert len(catalog.game.world.weathers) == 6
