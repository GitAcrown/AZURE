"""Dossiers d'identification et Fortune."""

from __future__ import annotations

from pathlib import Path

from common.catalog import load_catalog
from common.fishing import fortune_mult
from common.inspect import (
    inspect_item_text,
    inspect_species_text,
    species_context_line,
    species_where_text,
)
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
    dossier = inspect_species_text(catalog, perch, markdown=False)
    assert "12–40 cm" in dossier
    assert "0.04–1.4 kg" in dossier


def test_species_context_omits_open_windows_and_keeps_prefs() -> None:
    catalog = load_catalog(ASSETS)
    parrot = species_context_line(catalog, catalog.get_species("parrot_fish"))
    assert parrot.startswith("Océan")
    assert "sauf hiver" in parrot
    assert "jour" in parrot
    assert "préfère clair" in parrot
    assert "évite tempête" in parrot
    assert "printemps" not in parrot

    mackerel = species_context_line(catalog, catalog.get_species("mackerel"))
    assert mackerel.startswith("Océan")
    assert "sauf" not in mackerel
    assert "aube" not in mackerel
    assert "préfère vent, nuageux" in mackerel
    assert "évite brouillard" in mackerel

    tuna = species_context_line(catalog, catalog.get_species("tuna"))
    assert "été, automne" in tuna
    assert "évite brouillard" in tuna
    assert "jour" not in tuna

    guppy = species_where_text(catalog, catalog.get_species("guppy"))
    assert guppy.startswith("**Où** · **Rivière**")
    assert "printemps, été" in guppy
    assert "préfère clair" in guppy


def test_dex_shows_habitat_only_when_discovered() -> None:
    from cogs.azure.views import _dex_page_lines, _dex_species
    from common.display import italic_text
    from common.player.models import DexRow

    catalog = load_catalog(ASSETS)
    chunk = _dex_species(catalog, "fishdex")[:4]
    caught = chunk[0]
    lines = _dex_page_lines(
        catalog,
        {
            caught.key: DexRow(
                species_key=caught.key,
                catch_count=2,
                first_caught_at="",
                best_length_cm=30.0,
            )
        },
        chunk,
    )
    habitat = italic_text(species_context_line(catalog, caught))
    assert habitat in lines
    hidden = [
        italic_text(species_context_line(catalog, spec))
        for spec in chunk[1:]
        if italic_text(species_context_line(catalog, spec)) != habitat
    ]
    assert hidden
    assert not any(line in lines for line in hidden)
    assert sum(1 for ln in lines if "???" in ln) == 3
