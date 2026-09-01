"""Quête du jour (avis sur la Place) — fonctions pures."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from common.catalog import Catalog
from common.world import milieu_at_phrase
from common.world.engine import localize


def daily_day_key(catalog: Catalog, now: datetime | None = None) -> str:
    return localize(now, catalog.game.world).date().isoformat()


def daily_milieu_key(
    catalog: Catalog, guild_id: int, *, now: datetime | None = None
) -> str:
    keys = [m.key for m in catalog.milieus]
    if not keys:
        raise ValueError("aucun milieu dans le catalogue")
    seed = f"{int(guild_id)}:{daily_day_key(catalog, now)}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return keys[int.from_bytes(digest[:8], "big") % len(keys)]


def daily_milieu_phrase(catalog: Catalog, milieu_key: str) -> str:
    try:
        milieu = catalog.get_milieu(milieu_key)
        return milieu_at_phrase(milieu.key, milieu.name)
    except Exception:
        return milieu_key


@dataclass(frozen=True)
class DailyStatus:
    day_key: str
    milieu_key: str
    count: int
    target: int
    rewarded: bool
    reward_bronze: int
    guild_count: int = 0
    guild_target: int = 0
    guild_done: bool = False
    guild_just_completed: bool = False

    @property
    def done(self) -> bool:
        return self.rewarded or self.count >= self.target


def daily_counters_text(
    catalog: Catalog,
    *,
    count: int,
    target: int,
    done: bool,
    guild_count: int,
    guild_target: int,
    guild_done: bool = False,
) -> str:
    you = "faite" if done else f"{count}/{target}"
    village_target = guild_target or int(catalog.game.daily.guild_catch_count)
    village_done = guild_done or (village_target > 0 and guild_count >= village_target)
    village = "faite" if village_done else f"{guild_count}/{village_target}"
    return f"**toi {you}** · **village {village}**"


def daily_place_block(catalog: Catalog, status: DailyStatus) -> str:
    phrase = daily_milieu_phrase(catalog, status.milieu_key)
    bits = daily_counters_text(
        catalog,
        count=status.count,
        target=status.target,
        done=status.done,
        guild_count=status.guild_count,
        guild_target=status.guild_target,
        guild_done=status.guild_done,
    )
    return f"**Quête du jour**\n{status.target} prises à {phrase} · {bits}"


def daily_talk_line(catalog: Catalog, guild_id: int, *, now: datetime | None = None) -> str:
    key = daily_milieu_key(catalog, guild_id, now=now)
    phrase = daily_milieu_phrase(catalog, key)
    settings = catalog.game.daily
    return (
        f"Quête du jour (avis sur la Place, objectif village) : "
        f"{settings.catch_count} prises gardées à {phrase} chacun "
        f"({settings.reward_bronze} bronze une fois). "
        f"Le village vise {settings.guild_catch_count} prises au total "
        f"(+{settings.guild_reward_env} note environnementale quand c'est fait)."
    )
