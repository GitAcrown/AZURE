"""Moteur de rencontres AZURE (fonctions pures, seedable)."""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from common.catalog import Catalog, FishingSettings, Item, Species
from common.world import world_state


class FishingError(Exception):
    pass


_LOOT_SOURCES = frozenset(
    {"rare_loot", "rare_fishing_loot", "very_rare_fishing_loot", "very_rare_loot"}
)
_BAD_WEATHER = frozenset({"rain", "storm", "wind"})


@dataclass(frozen=True)
class EncounterContext:
    milieu_key: str
    method: str
    season: str
    time_of_day: str
    weather_key: str
    bait: Item | None = None
    hook: Item | None = None
    ignore_night_penalty: bool = False
    offseason_bonus: float = 0.0
    env_quality_mult: float = 1.0
    fortune_mult: float = 1.0


@dataclass(frozen=True)
class WeightedEntry:
    species: Species
    weight: float


def context_from_world(
    catalog: Catalog,
    guild_id: int,
    milieu_key: str,
    method: str,
    *,
    bait: Item | None = None,
    hook: Item | None = None,
    ignore_night_penalty: bool = False,
    offseason_bonus: float = 0.0,
    env_quality_mult: float = 1.0,
    fortune_mult: float = 1.0,
) -> EncounterContext:
    state = world_state(catalog.game.world, guild_id, [milieu_key])
    return EncounterContext(
        milieu_key=milieu_key,
        method=method,
        season=state.season,
        time_of_day=state.time_of_day,
        weather_key=state.weathers[milieu_key].key,
        bait=bait,
        hook=hook,
        ignore_night_penalty=ignore_night_penalty,
        offseason_bonus=offseason_bonus,
        env_quality_mult=env_quality_mult,
        fortune_mult=fortune_mult,
    )


def _tag_multipliers(item: Item | None) -> dict[str, float]:
    if item is None:
        return {}
    raw = (item.effects or {}).get("encounter_tag_multipliers") or {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _apply_tags(weight: float, tags: list[str], multipliers: dict[str, float]) -> float:
    for tag in tags:
        if tag in multipliers:
            weight *= multipliers[tag]
    return weight


def _rarity_weight(rarity: str, settings: FishingSettings) -> float:
    weights = settings.rarity_weights
    if rarity in weights:
        return float(weights[rarity])
    if "uncommon" in weights:
        return float(weights["uncommon"])
    return next(iter(weights.values()))


def eligible(species: Species, ctx: EncounterContext) -> bool:
    if species.environment != ctx.milieu_key:
        return False
    if species.capture.method != ctx.method:
        return False
    seasons = species.availability.seasons
    if seasons and ctx.season not in seasons and ctx.offseason_bonus <= 0:
        return False
    times = species.availability.time
    if times and ctx.time_of_day not in times:
        return False
    required = species.availability.weather_required
    if required and ctx.weather_key not in required:
        return False
    return True


def species_weight(
    species: Species,
    ctx: EncounterContext,
    settings: FishingSettings,
) -> float:
    weight = _rarity_weight(species.rarity, settings)
    avail = species.availability
    if ctx.weather_key in avail.weather_preferred:
        weight *= settings.weather_preferred_mult
    if ctx.weather_key in avail.weather_avoided:
        weight *= settings.weather_avoided_mult
    bait_tags = list(dict.fromkeys([*species.tags, *species.capture.bait_tags]))
    hook_tags = list(dict.fromkeys([*species.tags, *species.capture.hook_tags]))
    weight = _apply_tags(weight, bait_tags, _tag_multipliers(ctx.bait))
    weight = _apply_tags(weight, hook_tags, _tag_multipliers(ctx.hook))
    if avail.seasons and ctx.season not in avail.seasons and ctx.offseason_bonus > 0:
        weight *= ctx.offseason_bonus
    if ctx.time_of_day == "night" and not ctx.ignore_night_penalty:
        weight *= settings.night_weight_mult
    if species.rarity != "common" and ctx.env_quality_mult != 1.0:
        try:
            weight *= float(ctx.env_quality_mult)
        except (TypeError, ValueError):
            pass
    if species.rarity != "common" and ctx.fortune_mult != 1.0:
        try:
            weight *= float(ctx.fortune_mult)
        except (TypeError, ValueError):
            pass
    return weight


def build_pool(catalog: Catalog, ctx: EncounterContext) -> list[WeightedEntry]:
    settings = catalog.game.fishing
    pool: list[WeightedEntry] = []
    for species in catalog.species:
        if not eligible(species, ctx):
            continue
        weight = species_weight(species, ctx, settings)
        if weight <= 0:
            continue
        pool.append(WeightedEntry(species=species, weight=weight))
    return pool


def roll(pool: list[WeightedEntry], rng: random.Random) -> Species:
    if not pool:
        raise FishingError("cet outil ne prend rien ici")
    picks = rng.choices(
        [entry.species for entry in pool],
        weights=[entry.weight for entry in pool],
        k=1,
    )
    return picks[0]


def waste_items(catalog: Catalog) -> list[Item]:
    return [it for it in catalog.items if it.enabled and it.category == "waste"]


def waste_weight(item: Item) -> float:
    sources = set(item.sources or [])
    flags = set(item.flags or [])
    if "very_rare_fishing_loot" in sources:
        return 2.0
    if "rare" in flags or "rare_fishing_loot" in sources:
        return 10.0
    if "common_waste" in flags or "fishing_loot" in sources:
        return 100.0
    return 40.0


def roll_waste(catalog: Catalog, rng: random.Random) -> Item | None:
    chance = float(catalog.game.fishing.waste_chance)
    if chance <= 0 or rng.random() >= chance:
        return None
    pool = waste_items(catalog)
    if not pool:
        return None
    return rng.choices(pool, weights=[waste_weight(it) for it in pool], k=1)[0]


def item_is_gem(item: Item) -> bool:
    col = item.collection
    return col is not None and col.collectible and col.group == "gemstones"


def gem_items(catalog: Catalog) -> list[Item]:
    return [it for it in catalog.items if it.enabled and item_is_gem(it)]


def unique_gem_count(catalog: Catalog, owned: set[str]) -> int:
    return sum(1 for it in gem_items(catalog) if it.key in owned)


def fortune_mult(catalog: Catalog, owned: set[str]) -> float:
    n = unique_gem_count(catalog, owned)
    if n <= 0:
        return 1.0
    return 1.0 + float(catalog.game.fishing.gem_fortune_per_badge) * n


def loot_items(catalog: Catalog) -> list[Item]:
    out: list[Item] = []
    for it in catalog.items:
        if not it.enabled:
            continue
        if it.category == "waste":
            continue
        if item_is_gem(it):
            continue
        if _LOOT_SOURCES.intersection(it.sources or []):
            out.append(it)
    return out


def loot_weight(item: Item) -> float:
    sources = set(item.sources or [])
    if "very_rare_fishing_loot" in sources or "very_rare_loot" in sources:
        return 2.0
    if "rare_loot" in sources or "rare_fishing_loot" in sources:
        return 10.0
    return 5.0


def roll_loot(catalog: Catalog, rng: random.Random) -> Item | None:
    chance = float(catalog.game.fishing.loot_chance)
    if chance <= 0 or rng.random() >= chance:
        return None
    pool = loot_items(catalog)
    if not pool:
        return None
    return rng.choices(pool, weights=[loot_weight(it) for it in pool], k=1)[0]


def gem_weight(item: Item) -> float:
    col = item.collection
    prestige = int(col.prestige_value) if col is not None and col.prestige_value else 1
    return max(1.0, 8.0 - float(prestige))


def roll_gem(catalog: Catalog, rng: random.Random) -> Item | None:
    chance = float(catalog.game.fishing.gem_chance)
    if chance <= 0 or rng.random() >= chance:
        return None
    pool = gem_items(catalog)
    if not pool:
        return None
    return rng.choices(pool, weights=[gem_weight(it) for it in pool], k=1)[0]


def weather_energy_extra(catalog: Catalog, weather_key: str, *, ignore: bool) -> int:
    if ignore or weather_key not in _BAD_WEATHER:
        return 0
    extra = int(catalog.game.fishing.bad_weather_energy_extra)
    if weather_key == "wind":
        return max(1, extra // 2)
    return extra


def cast_energy_parts(
    catalog: Catalog, weather_key: str, *, ignore: bool = False
) -> tuple[int, int]:
    """`(coût de base, extra météo)`."""
    base = max(0, int(catalog.game.fishing.cast_energy_cost))
    extra = weather_energy_extra(catalog, weather_key, ignore=ignore)
    return base, extra


def energy_shortfall_message(
    *,
    energy: int,
    base: int,
    extra: int = 0,
    weather_label: str = "",
) -> str:
    cost = base + extra
    if extra and weather_label:
        return (
            f"pas assez d'énergie — {weather_label} ajoute **+{extra}** "
            f"· il faut **{cost}**, tu as **{energy}**"
        )
    return f"pas assez d'énergie — il faut **{cost}**, tu as **{energy}**"


def simulate(
    catalog: Catalog,
    ctx: EncounterContext,
    n: int,
    rng: Optional[random.Random] = None,
) -> Counter[str]:
    if n < 1:
        raise FishingError("n doit être ≥ 1")
    pool = build_pool(catalog, ctx)
    if not pool:
        raise FishingError("cet outil ne prend rien ici")
    rng = rng or random.Random()
    counts: Counter[str] = Counter()
    for _ in range(n):
        counts[roll(pool, rng).key] += 1
    return counts
