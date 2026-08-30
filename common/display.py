"""Libellés d'affichage AZURE (noms d'items, descriptions)."""

from __future__ import annotations

import re

from common.asset_emojis import item_emoji, species_emoji, with_emoji
from common.catalog import Catalog
from common.catalog.models import WeatherKind

_ACTION_RE = re.compile(r"\([^()]{1,80}\)")


def bracket_name(name: str) -> str:
    """Nom d'item inline, mélangé à d'autre texte : **[Canne côtière]**."""
    return f"**[{name}]**"


def title_name(name: str) -> str:
    """Nom seul / titre : pas de crochets."""
    return f"## {name}"


def italic_text(text: str) -> str:
    """Description ou lore."""
    text = (text or "").strip()
    if not text:
        return ""
    return f"*{text}*"


def quote_text(text: str) -> str:
    """Bloc citation Discord, une `>` par ligne."""
    text = (text or "").strip()
    if not text:
        return ""
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.splitlines())


def dialogue_turn(speaker: str, text: str) -> str:
    """Réplique nommée : **Dan** puis la citation."""
    name = (speaker or "").strip() or "—"
    body = quote_text(text)
    if not body:
        return f"**{name}**"
    return f"**{name}**\n{body}"


def npc_speech_text(text: str) -> str:
    """Parole en italique, actions `(…)` en romain."""
    text = (text or "").strip()
    if not text:
        return ""
    chunks: list[str] = []
    last = 0
    for match in _ACTION_RE.finditer(text):
        spoken = _plain_for_italic(text[last:match.start()])
        if spoken:
            chunks.append(italic_text(spoken))
        chunks.append(match.group(0))
        last = match.end()
    spoken = _plain_for_italic(text[last:])
    if spoken:
        chunks.append(italic_text(spoken))
    return " ".join(chunks)


def _plain_for_italic(text: str) -> str:
    return text.replace("*", "").replace("_", "").strip()


def error_message(text: str) -> str:
    """Erreur en texte simple, sans LayoutView."""
    text = (text or "").strip()
    if text:
        text = text[0].upper() + text[1:]
    return f"**Erreur** — {text}"


def weather_display(weather: WeatherKind) -> str:
    """Météo avec emoji Unicode : `🌧️ pluie`."""
    name = (weather.name or weather.key or "—").lower()
    emoji = (weather.emoji or "").strip()
    if emoji:
        return f"{emoji} {name}"
    return name


def weather_of(catalog: Catalog, key: str) -> WeatherKind:
    for w in catalog.game.world.weathers:
        if w.key == key:
            return w
    return WeatherKind(key=key, name=key)


def item_display(
    catalog: Catalog,
    item_key: str,
    *,
    extra: str = "",
    emoji: bool = True,
    brackets: bool = True,
) -> str:
    """Emoji (optionnel) collé au nom. Crochets seulement s'il y a d'autre texte sur la ligne."""
    try:
        name = catalog.get_item(item_key).name
    except Exception:
        name = item_key
    if brackets or extra:
        text = f"{bracket_name(name)}{extra}"
    else:
        text = f"**{name}**"
    if not emoji:
        return text
    return with_emoji(item_emoji(item_key), text)


def species_display(
    catalog: Catalog,
    species_key: str,
    *,
    extra: str = "",
    emoji: bool = True,
    brackets: bool = True,
) -> str:
    """Même format que les items : **[Perche]**."""
    try:
        name = catalog.get_species(species_key).name
    except Exception:
        name = species_key
    if brackets or extra:
        text = f"{bracket_name(name)}{extra}"
    else:
        text = f"**{name}**"
    if not emoji:
        return text
    return with_emoji(species_emoji(species_key), text)
