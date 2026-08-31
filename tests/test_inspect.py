"""Dossiers d'identification et Fortune."""

from __future__ import annotations

from pathlib import Path

from common.catalog import load_catalog
from common.fishing import fortune_mult
from common.inspect import inspect_item_text, inspect_species_text
from common.player.models import CaughtSpecimen

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def test_fortune_is_two_percent_per_gem() -> None:
    catalog = load_catalog(ASSETS)
    assert catalog.game.fishing.gem_fortune_per_badge == 0.02
    assert fortune_mult(catalog, set()) == 1.0
    assert fortune_mult(catalog, {"red_gem"}) == 1.02
    assert fortune_mult(catalog, {"red_gem", "diamond"}) == 1.04
    assert fortune_mult(catalog, {"red_gem", "bread"}) == 1.02


def test_inspect_item_includes_stats() -> None:
    catalog = load_catalog(ASSETS)
    compass = catalog.get_item("compass")
    text = inspect_item_text(catalog, compass, markdown=False)
    assert "compass = Boussole" in text
    assert "marche" in text.lower()
    bread = catalog.get_item("bread")
    food = inspect_item_text(catalog, bread, markdown=False)
    assert "15 %" in food
    lantern = catalog.get_item("lantern")
    worn = inspect_item_text(catalog, lantern, remaining=10, markdown=False)
    assert "10/" in worn


def test_inspect_species_includes_specimen() -> None:
    catalog = load_catalog(ASSETS)
    perch = catalog.get_species("perch")
    spec = CaughtSpecimen(
        id=1, species_key="perch", length_cm=20.0, weight_kg=0.4, caught_at=""
    )
    text = inspect_species_text(catalog, perch, specimen=spec, markdown=False)
    assert "20 cm" in text
    assert "0.4 kg" in text
    assert "perch =" in text
