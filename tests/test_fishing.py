"""Tests du moteur de rencontres (sans Discord)."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from common.catalog import load_catalog
from common.catalog.models import (
    FishingSettings,
    Item,
    MinigameSettings,
    Species,
    SpeciesAssets,
    SpeciesAvailability,
    SpeciesBiology,
    SpeciesCapture,
    SpecimenSettings,
)
from common.fishing import (
    EncounterContext,
    FishingError,
    bite_timings,
    build_pool,
    eligible,
    energy_shortfall_message,
    generate_specimen,
    hook_window_multiplier,
    roll,
    roll_loot,
    simulate,
    species_weight,
)

ROOT = Path(__file__).resolve().parents[1]


def _species(
    *,
    key: str = "test_fish",
    environment: str = "ocean",
    method: str = "rod",
    rarity: str = "common",
    tags: list[str] | None = None,
    seasons: list[str] | None = None,
    time: list[str] | None = None,
    weather_required: list[str] | None = None,
    weather_preferred: list[str] | None = None,
    weather_avoided: list[str] | None = None,
    bait_tags: list[str] | None = None,
) -> Species:
    return Species(
        id=1,
        key=key,
        name=key,
        category="fish",
        environment=environment,
        assets=SpeciesAssets(sprite="specie1.png", shadow="specie1_s.png"),
        capture=SpeciesCapture(method=method, bait_tags=bait_tags or []),
        availability=SpeciesAvailability(
            seasons=seasons or [],
            time=time or [],
            weather_required=weather_required or [],
            weather_preferred=weather_preferred or [],
            weather_avoided=weather_avoided or [],
        ),
        rarity=rarity,
        tags=tags or [],
    )


def _ctx(**kwargs) -> EncounterContext:
    base = dict(
        milieu_key="ocean",
        method="rod",
        season="summer",
        time_of_day="day",
        weather_key="clear",
    )
    base.update(kwargs)
    return EncounterContext(**base)


def test_eligible_filters_milieu_method_season() -> None:
    fish = _species(seasons=["winter"])
    assert eligible(fish, _ctx(season="winter"))
    assert not eligible(fish, _ctx(season="summer"))
    assert not eligible(fish, _ctx(milieu_key="pond"))
    assert not eligible(fish, _ctx(method="net"))


def test_eligible_weather_required() -> None:
    fish = _species(weather_required=["rain"])
    assert eligible(fish, _ctx(weather_key="rain"))
    assert not eligible(fish, _ctx(weather_key="clear"))


def test_rarity_and_weather_and_bait_weights() -> None:
    settings = FishingSettings()
    common = _species(rarity="common")
    rare = _species(rarity="rare")
    ctx = _ctx()
    assert species_weight(common, ctx, settings) == 100
    assert species_weight(rare, ctx, settings) == 12
    assert species_weight(rare, _ctx(env_quality_mult=1.4), settings) == pytest.approx(16.8)
    assert species_weight(common, _ctx(env_quality_mult=1.4), settings) == 100
    assert species_weight(rare, _ctx(env_quality_mult=0.6), settings) == pytest.approx(7.2)

    preferred = _species(weather_preferred=["clear"])
    avoided = _species(weather_avoided=["clear"])
    assert species_weight(preferred, ctx, settings) == pytest.approx(125)
    assert species_weight(avoided, ctx, settings) == pytest.approx(50)

    tagged = _species(tags=["predator"])
    bait = Item(
        id=99,
        key="test_bait",
        name="Test",
        category="bait",
        sprite="item1.png",
        effects={"encounter_tag_multipliers": {"predator": 2.0}},
    )
    boosted = species_weight(tagged, _ctx(bait=bait), settings)
    assert boosted == pytest.approx(200)
    assert species_weight(tagged, ctx, settings) == 100


def test_night_penalty_and_offseason() -> None:
    settings = FishingSettings()
    fish = _species()
    day = species_weight(fish, _ctx(), settings)
    night = species_weight(fish, _ctx(time_of_day="night"), settings)
    assert night == pytest.approx(day * settings.night_weight_mult)
    lantern = species_weight(
        fish, _ctx(time_of_day="night", ignore_night_penalty=True), settings
    )
    assert lantern == pytest.approx(day)
    winter = _species(seasons=["winter"])
    assert not eligible(winter, _ctx(season="summer"))
    assert eligible(winter, _ctx(season="summer", offseason_bonus=0.05))
    assert species_weight(
        winter, _ctx(season="summer", offseason_bonus=0.05), settings
    ) == pytest.approx(5)


def test_king_salmon_autumn_only() -> None:
    catalog = load_catalog(ROOT / "assets")
    summer = build_pool(catalog, _ctx(milieu_key="river", method="rod", season="summer"))
    autumn = build_pool(catalog, _ctx(milieu_key="river", method="rod", season="autumn"))
    assert "king_salmon" not in {e.species.key for e in summer}
    assert "king_salmon" in {e.species.key for e in autumn}


def test_roll_loot_independent_of_waste() -> None:
    catalog = load_catalog(ROOT / "assets")

    class _Hit:
        def random(self) -> float:
            return 0.0

        def choices(self, pop, weights=None, k=1):
            return [pop[0]]

    loot = roll_loot(catalog, _Hit())
    assert loot is not None
    assert loot.category != "waste"
    from common.fishing import item_is_gem, roll_gem

    assert not item_is_gem(loot)
    gem = roll_gem(catalog, _Hit())
    assert gem is not None
    assert item_is_gem(gem)


def test_ocean_rod_and_net_pools_disjoint() -> None:
    catalog = load_catalog(ROOT / "assets")
    rod = build_pool(catalog, _ctx(method="rod"))
    net = build_pool(catalog, _ctx(method="net"))
    assert rod
    assert net
    assert all(e.species.environment == "ocean" for e in rod)
    assert all(e.species.capture.method == "rod" for e in rod)
    assert all(e.species.capture.method == "net" for e in net)
    assert {e.species.key for e in rod}.isdisjoint({e.species.key for e in net})


def test_roll_seed_reproducible() -> None:
    catalog = load_catalog(ROOT / "assets")
    pool = build_pool(catalog, _ctx())
    a = roll(pool, random.Random(42))
    b = roll(pool, random.Random(42))
    c = roll(pool, random.Random(7))
    assert a.key == b.key
    assert c.key  # just a valid pick


def test_simulate_counts_and_empty_pool() -> None:
    catalog = load_catalog(ROOT / "assets")
    counts = simulate(catalog, _ctx(), 200, rng=random.Random(1))
    assert sum(counts.values()) == 200
    assert counts
    with pytest.raises(FishingError, match="ne prend rien"):
        simulate(catalog, _ctx(method="harpoon"), 10)
    with pytest.raises(FishingError, match="ne prend rien"):
        roll([], random.Random(1))


def test_bite_timings_rod_vs_net() -> None:
    settings = MinigameSettings()
    net = bite_timings(settings, "net")
    assert net.trap_early is False
    assert net.action_label == "Ramasser"
    assert net.window_s == settings.net_window_s
    rod = bite_timings(settings, "rod", rng=random.Random(1))
    assert rod.trap_early is True
    assert rod.action_label == "Ferrer"
    assert settings.rod_wait_min_s <= rod.wait_s <= settings.rod_wait_max_s
    hook = Item(
        id=28,
        key="big_hook",
        name="Gros",
        category="hook",
        sprite="item28.png",
        effects={"minigame": {"hook_window_multiplier": 0.5}},
    )
    tight = bite_timings(settings, "rod", hook=hook, rng=random.Random(1))
    assert tight.window_s == pytest.approx(settings.rod_window_s * 0.5)
    assert hook_window_multiplier(None) == 1.0


def test_generate_specimen_fallback_and_yaml_range() -> None:
    settings = SpecimenSettings()
    fish = _species()
    spec = generate_specimen(fish, settings, random.Random(1))
    lo, hi = settings.fallback_length_cm
    assert lo <= spec.length_cm <= hi
    wlo, whi = settings.fallback_weight_kg
    assert wlo <= spec.weight_kg <= whi
    a = generate_specimen(fish, settings, random.Random(3))
    b = generate_specimen(fish, settings, random.Random(3))
    assert a == b
    ranged = Species(
        id=2,
        key="ranged",
        name="ranged",
        category="fish",
        environment="ocean",
        assets=SpeciesAssets(sprite="specie1.png", shadow="specie1_s.png"),
        capture=SpeciesCapture(method="rod"),
        biology=SpeciesBiology(
            min_length_cm=20,
            max_length_cm=22,
            min_weight_kg=0.4,
            max_weight_kg=0.5,
        ),
    )
    got = generate_specimen(ranged, settings, random.Random(0))
    assert 20 <= got.length_cm <= 22
    assert 0.4 <= got.weight_kg <= 0.5


def test_energy_shortfall_mentions_weather() -> None:
    plain = energy_shortfall_message(energy=3, base=8)
    assert "il faut **8** énergie" in plain
    assert "tu as **3**" in plain
    assert "météo" not in plain
    wet = energy_shortfall_message(
        energy=10, base=8, extra=4, weather_label="🌧️ pluie"
    )
    assert "🌧️ pluie" in wet
    assert "**+4** énergie" in wet
    assert "il faut **12** énergie" in wet
    assert "tu as **10**" in wet
