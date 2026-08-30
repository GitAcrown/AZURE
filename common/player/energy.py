"""Regen et buffs d'énergie (fonctions pures)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def bonus_pct_at(pct: float, until: datetime | None, now: datetime) -> float:
    if pct <= 0 or until is None or now >= until:
        return 0.0
    return float(pct)


def effective_energy_max(base: int, pct: float, until: datetime | None, now: datetime) -> int:
    active = bonus_pct_at(pct, until, now)
    if active <= 0:
        return max(1, int(base))
    return max(1, int(round(base * (1 + active))))


def coffee_minutes_left(until: datetime | None, now: datetime) -> int | None:
    if until is None or now >= until:
        return None
    seconds = (until - now).total_seconds()
    return max(1, int(seconds // 60)) if seconds > 0 else None


def regen_energy(
    energy: int,
    eff_max: int,
    updated_at: datetime | None,
    now: datetime,
    per_hour: float,
) -> tuple[int, datetime]:
    """Points entiers ; le reste de secondes reste sur `updated_at`."""
    if updated_at is None:
        return min(energy, eff_max), now
    energy = min(energy, eff_max)
    if per_hour <= 0 or energy >= eff_max:
        return energy, now if energy >= eff_max else updated_at
    seconds_per_point = 3600.0 / per_hour
    elapsed = (now - updated_at).total_seconds()
    if elapsed < seconds_per_point:
        return energy, updated_at
    gain = int(elapsed // seconds_per_point)
    if gain <= 0:
        return energy, updated_at
    new_energy = min(eff_max, energy + gain)
    applied = min(gain, new_energy - energy)
    new_updated = updated_at + timedelta(seconds=applied * seconds_per_point)
    if new_energy >= eff_max:
        new_updated = now
    return new_energy, new_updated
