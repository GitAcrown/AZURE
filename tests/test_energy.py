"""Tests regen d'énergie (sans SQLite)."""

from datetime import datetime, timedelta, timezone

from common.player.energy import effective_energy_max, regen_energy

NOW = datetime(2026, 8, 30, 19, 0, tzinfo=timezone.utc)


def test_regen_grants_whole_points() -> None:
    updated = NOW - timedelta(minutes=9)
    energy, new_at = regen_energy(50, 100, updated, NOW, per_hour=20)
    # 20/h → 3 min / point ; 9 min → 3 points
    assert energy == 53
    assert new_at == updated + timedelta(minutes=9)


def test_regen_caps_at_max() -> None:
    updated = NOW - timedelta(hours=10)
    energy, new_at = regen_energy(90, 100, updated, NOW, per_hour=20)
    assert energy == 100
    assert new_at == NOW


def test_regen_none_when_full() -> None:
    energy, new_at = regen_energy(100, 100, NOW - timedelta(hours=1), NOW, per_hour=20)
    assert energy == 100
    assert new_at == NOW


def test_effective_max_coffee() -> None:
    until = NOW + timedelta(minutes=30)
    assert effective_energy_max(100, 0.2, until, NOW) == 120
    assert effective_energy_max(100, 0.2, NOW - timedelta(seconds=1), NOW) == 100
