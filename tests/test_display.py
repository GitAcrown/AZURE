"""Libellés d'items dans les menus."""

from pathlib import Path

from common.catalog import load_catalog
from common.catalog.models import WeatherKind
from common.display import (
    bracket_name,
    dialogue_turn,
    energy_amount,
    error_message,
    italic_text,
    item_display,
    species_display,
    npc_speech_text,
    quote_text,
    title_name,
    weather_display,
    weather_of,
)

ROOT = Path(__file__).resolve().parents[1]


def test_bracket_name() -> None:
    assert bracket_name("Canne côtière") == "**[Canne côtière]**"


def test_title_name_has_no_brackets() -> None:
    assert title_name("Canne côtière") == "## Canne côtière"
    assert "[" not in title_name("Canne côtière")


def test_italic_text() -> None:
    assert italic_text("Une canne légère.") == "*Une canne légère.*"
    assert italic_text("  ") == ""


def test_npc_speech_text() -> None:
    assert npc_speech_text("Allé, on y va.") == "*Allé, on y va.*"
    assert npc_speech_text("(Tape du bec) Allé.") == "(Tape du bec) *Allé.*"
    assert npc_speech_text("(Hoche le crâne.)") == "(Hoche le crâne.)"
    assert npc_speech_text("") == ""


def test_dialogue_turn() -> None:
    assert quote_text("Allé.") == "> Allé."
    assert dialogue_turn("Toi", "T'as du pain ?") == "**Toi**\n> T'as du pain ?"
    assert dialogue_turn("Dan", npc_speech_text("(Hoche la tête.) Oui.")) == (
        "**Dan**\n> (Hoche la tête.) *Oui.*"
    )


def test_error_message() -> None:
    assert error_message("pas assez d'énergie") == "**Erreur** — Pas assez d'énergie"
    assert error_message("AZURE n'est pas prêt.") == "**Erreur** — AZURE n'est pas prêt."


def test_weather_display_uses_unicode() -> None:
    catalog = load_catalog(ROOT / "assets")
    rain = weather_of(catalog, "rain")
    assert rain.emoji == "🌧️"
    assert weather_display(rain) == "🌧️ pluie"
    assert weather_display(WeatherKind(key="clear", name="Clair", emoji="☀️")).startswith("☀")
    unknown = weather_of(catalog, "space-weather")
    assert weather_display(unknown) == "space-weather"


def test_item_display_uses_catalog_name() -> None:
    catalog = load_catalog(ROOT / "assets")
    assert item_display(catalog, "coastal_rod", emoji=False) == "**[Canne côtière]**"
    assert item_display(catalog, "coastal_rod", extra=" ×2", emoji=False) == "**[Canne côtière]** ×2"
    assert item_display(catalog, "coastal_rod", emoji=False, brackets=False) == "**Canne côtière**"
    text = item_display(catalog, "coastal_rod")
    assert "**[Canne côtière]**" in text


def test_species_display_matches_item_style() -> None:
    catalog = load_catalog(ROOT / "assets")
    assert species_display(catalog, "perch", emoji=False) == "**[Perche]**"
    assert (
        species_display(catalog, "perch", extra=" · `20 cm`", emoji=False)
        == "**[Perche]** · `20 cm`"
    )


def test_energy_amount_always_says_energy() -> None:
    assert energy_amount(8) == "**8** énergie"
    assert energy_amount(12) == "**12** énergie"
