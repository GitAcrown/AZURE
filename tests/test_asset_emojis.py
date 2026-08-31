"""Jobs d'emojis d'application dérivés du catalogue."""

from __future__ import annotations

from pathlib import Path

from common.asset_emojis import item_is_collectible, iter_emoji_jobs, paginate_gallery
from common.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def test_emoji_jobs_cover_species_items_and_ui() -> None:
    catalog = load_catalog(ASSETS)
    jobs = iter_emoji_jobs(catalog)

    species_sprite = [j for j in jobs if j.kind == "species" and j.variant == "sprite"]
    species_shadow = [j for j in jobs if j.kind == "species" and j.variant == "shadow"]
    item_sprite = [j for j in jobs if j.kind == "items" and j.variant == "sprite"]
    item_shadow = [j for j in jobs if j.kind == "items" and j.variant == "shadow"]
    ui = [j for j in jobs if j.kind == "ui"]
    npcs = [j for j in jobs if j.kind == "npcs"]

    assert len(species_sprite) == 114
    assert len(species_shadow) == 114
    assert len(item_sprite) == 50
    collectible = [it for it in catalog.items if item_is_collectible(it) and it.shadow]
    assert len(item_shadow) == len(collectible)
    assert len(item_shadow) >= 14
    assert len(ui) == 9
    assert {j.key for j in ui} >= {"LEFT", "RIGHT", "COIN1", "MEDAL1"}
    assert len(npcs) == 13
    assert all(j.path.is_file() for j in jobs)

    names = [j.discord_name for j in jobs]
    assert len(names) == len(set(names))


def test_paginate_gallery_splits_and_keeps_headers() -> None:
    sections = [("UI", ["a"] * 5), ("Items", ["b"] * 10)]
    pages = paginate_gallery(sections, page_size=8)
    assert len(pages) == 2
    assert pages[0][0] == ("UI", ["a"] * 5)
    assert pages[0][1][0] == "Items"
    assert pages[0][1][1] == ["b"] * 3
    assert pages[1][0] == ("Items (suite)", ["b"] * 7)


def test_paginate_gallery_empty() -> None:
    assert paginate_gallery([]) == []


def test_collectible_gems_get_shadow_emoji() -> None:
    catalog = load_catalog(ASSETS)
    jobs = {(j.key, j.variant) for j in iter_emoji_jobs(catalog) if j.kind == "items"}
    assert ("red_gem", "sprite") in jobs
    assert ("red_gem", "shadow") in jobs
    assert ("coastal_rod", "sprite") in jobs
    assert ("coastal_rod", "shadow") not in jobs
    gems = [
        it
        for it in catalog.items
        if it.collection is not None and it.collection.group == "gemstones"
    ]
    assert len(gems) == 7
    assert all(item_is_collectible(g) for g in gems)
    assert not item_is_collectible(catalog.get_item("coastal_rod"))
    assert item_is_collectible(catalog.get_item("normal_skull"))
