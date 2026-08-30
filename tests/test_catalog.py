"""Tests du catalogue de contenu AZURE (sans Discord)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from common.catalog import CatalogError, load_catalog

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

MINI_SPECIES = {
    "id": 1,
    "key": "test_fish",
    "name": "Poisson test",
    "category": "fish",
    "environment": "ocean",
    "assets": {"sprite": "specie1.png", "shadow": "specie1_s.png"},
    "capture": {"method": "rod"},
    "tags": [],
    "biology": {
        "min_length_cm": None,
        "max_length_cm": None,
        "min_weight_kg": None,
        "max_weight_kg": None,
    },
}

MINI_ITEM = {
    "id": 1,
    "key": "test_rod",
    "name": "Canne test",
    "category": "tool",
    "sprite": "item1.png",
    "shadow": "item1_s.png",
    "shadow_ready": True,
    "enabled": True,
    "sources": ["starter"],
    "equipment": {"equippable": True, "mode": "active", "slot": "tool", "capture_method": "rod"},
}

MINI_NPC = {
    "id": 1,
    "key": "npc1",
    "name": None,
    "role": None,
    "enabled": False,
    "portraits": {"default": "portrait1.png", "alt": None},
}

MINI_MILIEUS = [
    {"id": 1, "key": "ocean", "name": "Océan", "description": "Mer"},
    {"id": 2, "key": "river", "name": "Rivière", "description": "Fleuve"},
    {"id": 3, "key": "pond", "name": "Étang", "description": "Mare"},
]


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"png")


def _dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)


def build_mini_assets(
    root: Path,
    *,
    species: list[dict] | None = None,
    items: list[dict] | None = None,
    npcs: list[dict] | None = None,
    milieus: list[dict] | None = None,
    create_files: bool = True,
) -> Path:
    species = species if species is not None else [MINI_SPECIES]
    items = items if items is not None else [MINI_ITEM]
    npcs = npcs if npcs is not None else [MINI_NPC]
    milieus = milieus if milieus is not None else MINI_MILIEUS

    _dump(root / "species" / "species.yaml", {"schema_version": 2, "species": species})
    _dump(root / "items" / "items.yaml", {"schema_version": 1, "items": items})
    _dump(root / "npcs" / "npcs.yaml", {"schema_version": 1, "npcs": npcs})
    _dump(root / "milieus" / "milieus.yaml", {"schema_version": 1, "milieus": milieus})
    _dump(
        root / "game.yaml",
        {
            "schema_version": 1,
            "money": {"bronze_per_silver": 100, "silver_per_gold": 100},
            "player": {"energy_max": 100, "energy_start": 100, "money_start": 0},
        },
    )

    if create_files:
        for spec in species:
            assets = spec.get("assets") or {}
            if assets.get("sprite"):
                _touch(root / "species" / assets["sprite"])
            if assets.get("shadow"):
                _touch(root / "species" / assets["shadow"])
        for item in items:
            if item.get("sprite"):
                _touch(root / "items" / item["sprite"])
            if item.get("shadow") and item.get("shadow_ready", True):
                _touch(root / "items" / item["shadow"])
        for npc in npcs:
            portraits = npc.get("portraits") or {}
            for field in ("default", "alt", "good", "bad"):
                filename = portraits.get(field)
                if filename:
                    _touch(root / "npcs" / filename)
    return root


def test_load_real_catalog() -> None:
    catalog = load_catalog(ASSETS)
    assert len(catalog.species) == 114
    assert len(catalog.items) == 50
    assert len(catalog.milieus) == 3
    assert len(catalog.npcs) == 11
    assert {m.key for m in catalog.milieus} == {"ocean", "river", "pond"}
    assert catalog.game.player.energy_max == 100
    assert catalog.game.player.energy_start == 100
    assert catalog.game.player.money_start == 0
    assert catalog.game.player.fish_carry_capacity == 5
    assert catalog.game.player.non_fish_carry_capacity == 5
    assert catalog.game.world.timezone == "Europe/Paris"
    assert catalog.game.world.weather_bucket_minutes == 60
    assert catalog.game.village.environment_good_threshold == 50
    assert catalog.game.village.skull_summon_threshold == 10
    assert catalog.game.village.travel_cost == 20
    assert catalog.game.village.travel_minutes == 30
    assert catalog.game.village.bargain.buy_mult == 0.95
    assert catalog.game.village.bargain.sell_mult == 1.05
    assert catalog.game.fishing.waste_chance == 0.12
    assert catalog.game.fishing.loot_chance == 0.06
    assert catalog.game.fishing.cast_energy_cost == 8
    assert catalog.game.fishing.rarity_weights["common"] == 100
    assert catalog.game.fishing.minigame.rod_wait_min_s == 3.5
    assert catalog.game.fishing.minigame.rod_wait_max_s == 7.0
    assert catalog.game.fishing.minigame.rod_window_s == 2.0
    assert catalog.game.fishing.minigame.net_wait_s == 2.0
    assert catalog.game.fishing.minigame.net_window_s == 10.0
    assert catalog.game.fishing.specimen.fallback_length_cm == [10, 50]
    weathers = {w.key: w for w in catalog.game.world.weathers}
    assert set(weathers) == {"clear", "cloudy", "rain", "storm", "fog", "wind"}
    assert weathers["rain"].emoji == "🌧️"
    assert weathers["storm"].emoji == "⛈️"
    assert all(s.collection.recordable for s in catalog.species)


def test_lookup_species_by_key_and_id() -> None:
    catalog = load_catalog(ASSETS)
    by_key = catalog.get_species("parrot_fish")
    by_id = catalog.get_species(1)
    by_id_str = catalog.get_species("1")
    assert by_key is by_id is by_id_str
    assert by_key.name == "Poisson-perroquet"
    assert by_key.environment == "ocean"
    assert by_key.capture.method == "rod"


def test_lookup_item_and_starter() -> None:
    catalog = load_catalog(ASSETS)
    rod = catalog.get_item("coastal_rod")
    assert rod is catalog.get_item(1)
    assert rod.equipment is not None
    assert rod.equipment.slot == "tool"
    starters = catalog.items_by_source("starter", enabled_only=True)
    assert [it.key for it in starters] == ["coastal_rod", "widewater_rod", "net"]
    for key in ("coastal_rod", "widewater_rod", "net"):
        item = catalog.get_item(key)
        assert item.durability is None


def test_species_in_environment_and_method() -> None:
    catalog = load_catalog(ASSETS)
    ocean = catalog.species_in("ocean")
    ocean_rod = catalog.species_in("ocean", method="rod")
    ocean_net = catalog.species_in("ocean", method="net")
    assert len(ocean) == 66
    assert len(ocean_rod) + len(ocean_net) == len(ocean)
    assert all(s.environment == "ocean" for s in ocean)
    assert all(s.capture.method == "rod" for s in ocean_rod)


def test_disabled_items_remain_lookupable() -> None:
    catalog = load_catalog(ASSETS)
    lantern = catalog.get_item("jack_o_lantern")
    assert lantern.enabled is False
    enabled_events = catalog.items_by_category("event", enabled_only=True)
    assert all(it.enabled for it in enabled_events)
    assert lantern not in enabled_events


def test_named_village_npcs() -> None:
    catalog = load_catalog(ASSETS)
    gabriel = catalog.get_npc("gabriel")
    assert gabriel is catalog.get_npc(1)
    assert gabriel.name == "Gabriel"
    assert gabriel.role == "travel"
    assert gabriel.enabled is True
    unused = catalog.get_npc("npc5")
    assert unused.enabled is False
    assert unused.name is None
    gaia = catalog.get_npc("gaia")
    assert gaia.role == "special"
    assert gaia.portraits.good == "portrait10.png"
    assert gaia.portraits.bad == "portrait11.png"
    assert gaia.portrait_file(good=True) == "portrait10.png"
    assert gaia.portrait_file(good=False) == "portrait11.png"
    oz = catalog.get_npc("oz")
    assert oz.role == "summon"
    assert oz.portraits.good == "portrait12.png"
    assert oz.portraits.bad == "portrait13.png"
    shops = catalog.npcs_by_role("shop")
    assert {n.key for n in shops} == {"dan", "agathe", "joel"}
    dan = catalog.get_npc("dan")
    agathe = catalog.get_npc("agathe")
    joel = catalog.get_npc("joel")
    assert dan.shop_mode == "sell"
    assert agathe.shop_mode == "buy"
    assert joel.shop_mode == "sell"
    assert "bread" in dan.stock
    assert "lantern" in joel.stock
    lantern = catalog.get_item("lantern")
    assert lantern.equipment is not None
    assert lantern.equipment.slot == "objet"
    assert lantern.equipment.equippable is True
    compass = catalog.get_item("compass")
    assert compass.equipment is not None
    assert compass.equipment.slot == "objet"
    assert compass.effects.get("walk_time_mult") == 0.2
    assert "bread" not in joel.stock
    repairs = catalog.npcs_by_role("repair")
    assert {n.key for n in repairs} == {"maurice", "patrick"}
    travels = catalog.npcs_by_role("travel")
    assert {n.key for n in travels} == {"gabriel", "inti", "hedwig"}
    assert dan.hook
    assert "appâts" in dan.hook.lower() or "pain" in dan.hook.lower()
    assert oz.hook.startswith("(")
    assert "tôt" in dan.hook_for("dawn").lower()
    assert dan.hook_for("day") == dan.hook
    assert "noir" in catalog.get_npc("gabriel").hook_for("night").lower()
    for npc in catalog.npcs:
        if npc.enabled:
            assert npc.hook.strip(), npc.key
            for moment in ("dawn", "dusk", "night"):
                assert npc.hook_for(moment), f"{npc.key} {moment}"


def test_unknown_lookup_raises() -> None:
    catalog = load_catalog(ASSETS)
    with pytest.raises(CatalogError, match="introuvable"):
        catalog.get_species("no_such_fish")


def test_missing_asset_raises(tmp_path: Path) -> None:
    root = build_mini_assets(tmp_path)
    (root / "species" / "specie1.png").unlink()
    with pytest.raises(CatalogError, match="asset manquant"):
        load_catalog(root)


def test_duplicate_key_raises(tmp_path: Path) -> None:
    clone = dict(MINI_SPECIES)
    clone["id"] = 2
    root = build_mini_assets(tmp_path, species=[MINI_SPECIES, clone])
    with pytest.raises(CatalogError, match="key dupliquée"):
        load_catalog(root)


def test_unknown_environment_raises(tmp_path: Path) -> None:
    bad = dict(MINI_SPECIES)
    bad["environment"] = "swamp"
    root = build_mini_assets(tmp_path, species=[bad])
    with pytest.raises(CatalogError, match="milieu inconnu"):
        load_catalog(root)


def test_missing_yaml_raises(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="fichier introuvable"):
        load_catalog(tmp_path)


def test_shadow_optional_when_not_ready(tmp_path: Path) -> None:
    item = dict(MINI_ITEM)
    item["shadow"] = "item1_s.png"
    item["shadow_ready"] = False
    root = build_mini_assets(tmp_path, items=[item])
    (root / "items" / "item1_s.png").unlink(missing_ok=True)
    catalog = load_catalog(root)
    assert catalog.get_item("test_rod").shadow_ready is False
