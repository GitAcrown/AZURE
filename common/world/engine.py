"""Horloge et météo AZURE (fonctions pures, pas d'I/O Discord)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common.catalog.models import WeatherKind, WorldSettings

SEASON_LABELS = {
    "spring": "printemps",
    "summer": "été",
    "autumn": "automne",
    "winter": "hiver",
}

TIME_LABELS = {
    "dawn": "aube",
    "day": "jour",
    "dusk": "crépuscule",
    "night": "nuit",
}

AT_LABELS = {
    "ocean": "l'Océan",
    "river": "la Rivière",
    "pond": "l'Étang",
}


def zoneinfo_of(world: WorldSettings) -> ZoneInfo:
    try:
        return ZoneInfo(world.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"timezone inconnue : {world.timezone!r}") from exc


def localize(dt: datetime | None, world: WorldSettings) -> datetime:
    tz = zoneinfo_of(world)
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def season_at(dt: datetime, world: WorldSettings) -> str:
    local = localize(dt, world)
    month = local.month
    for key, months in world.seasons.items():
        if month in months:
            return key
    raise ValueError(f"aucun saison pour le mois {month}")


def time_of_day_at(dt: datetime, world: WorldSettings) -> str:
    local = localize(dt, world)
    hour = local.hour
    for key, bounds in world.time_windows.items():
        start, end = bounds
        if start < end:
            if start <= hour < end:
                return key
        elif hour >= start or hour < end:
            return key
    raise ValueError(f"aucune fenêtre horaire pour {hour}h")


def weather_bucket(dt: datetime, world: WorldSettings) -> int:
    local = localize(dt, world)
    minutes = world.weather_bucket_minutes
    return int(local.timestamp()) // (minutes * 60)


def next_bucket_at(dt: datetime, world: WorldSettings) -> datetime:
    local = localize(dt, world)
    bucket = weather_bucket(local, world)
    next_ts = (bucket + 1) * world.weather_bucket_minutes * 60
    return datetime.fromtimestamp(next_ts, tz=local.tzinfo)


def weather_at(guild_id: int, milieu_key: str, dt: datetime, world: WorldSettings) -> WeatherKind:
    bucket = weather_bucket(dt, world)
    digest = hashlib.sha256(f"{guild_id}:{milieu_key}:{bucket}".encode("utf-8")).digest()
    idx = int.from_bytes(digest[:8], "big") % len(world.weathers)
    return world.weathers[idx]


def season_label(key: str) -> str:
    return SEASON_LABELS.get(key, key)


def time_label(key: str) -> str:
    return TIME_LABELS.get(key, key)


def milieu_at_phrase(key: str, name: str) -> str:
    return AT_LABELS.get(key, name)


@dataclass(frozen=True)
class WorldState:
    at: datetime
    season: str
    time_of_day: str
    weathers: dict[str, WeatherKind]
    bucket: int
    next_bucket_at: datetime


def world_state(
    world: WorldSettings,
    guild_id: int,
    milieu_keys: list[str],
    *,
    at: datetime | None = None,
) -> WorldState:
    local = localize(at, world)
    return WorldState(
        at=local,
        season=season_at(local, world),
        time_of_day=time_of_day_at(local, world),
        weathers={key: weather_at(guild_id, key, local, world) for key in milieu_keys},
        bucket=weather_bucket(local, world),
        next_bucket_at=next_bucket_at(local, world),
    )
