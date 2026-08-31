"""Dossiers d'identification (items / espèces) — stats exactes pour Esmer."""

from __future__ import annotations

from typing import Any

from common.catalog import Catalog, Item, Species
from common.money import format_money
from common.player.models import CaughtSpecimen

SLOT_LABELS = {
    "tool": "Outil",
    "hook": "Crochet",
    "bait": "Appât",
    "objet": "Objet",
}

CATEGORY_LABELS = {
    "tool": "Outil",
    "hook": "Crochet",
    "bait": "Appât",
    "food": "Nourriture",
    "treasure": "Trésor",
    "collectible": "Collection",
    "fossil": "Fossile",
    "summon_currency": "Invocation",
    "passive": "Passif",
    "passive_item": "Passif",
    "waste": "Déchet",
    "diving": "Plongée",
    "event": "Événement",
}

RARITY_LABELS = {
    "common": "commune",
    "uncommon": "peu commune",
    "rare": "rare",
}

CAPTURE_LABELS = {
    "rod": "canne",
    "net": "filet",
}

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

COLLECTION_LABELS = {
    "gemstones": "gemmes (Fortune)",
    "fossil_replicas": "répliques fossiles",
}

TAG_LABELS = {
    "large": "gros",
    "small": "petits",
    "aggressive": "agressifs",
    "schooling": "en banc",
    "curious": "curieux",
    "light_attracted": "attirés par la lumière",
    "difficult": "difficiles",
    "predator": "prédateurs",
    "scavenger": "charognards",
    "herbivore": "herbivores",
    "worm_eater": "mangeurs de vers",
    "bottom_feeder": "fond",
    "insectivore": "insectivores",
    "opportunist": "opportunistes",
    "nocturnal": "nocturnes",
    "surface_feeder": "surface",
}

EFFECT_LABELS = {
    "restore_energy_pct": "énergie restaurée",
    "max_energy_bonus_pct": "bonus d'énergie max",
    "duration_minutes": "durée",
    "walk_time_mult": "durée de marche",
    "ignore_bad_weather_fatigue_penalty": "ignore la fatigue du mauvais temps",
    "ignore_night_fishing_success_penalty": "ignore le malus de pêche de nuit",
    "environment_cleanup_score": "note environnementale",
    "destination_weather_forecast_minutes": "prévision météo",
    "non_fish_carry_capacity_bonus": "places créatures / objets",
    "fish_carry_capacity_bonus": "places poissons",
    "guarantee_personal_record": "record personnel garanti",
    "record_axis": "axe du record",
    "respect_species_absolute_max": "respecte le max de l'espèce",
    "offseason_species_chance_bonus": "chance hors saison",
    "skeleton_summon_value": "valeur d'invocation",
}

MINIGAME_LABELS = {
    "hook_window_multiplier": "fenêtre d'accroche",
    "tension_tolerance_multiplier": "tolérance de tension",
    "escape_rate_multiplier": "fuite",
}


def _label(text: str, *, markdown: bool) -> str:
    return f"**{text}**" if markdown else text


def _line(label: str, value: str, *, markdown: bool) -> str:
    return f"{_label(label, markdown=markdown)} · {value}"


def _pct(value: float) -> str:
    n = float(value) * 100
    if abs(n - round(n)) < 0.05:
        return f"{int(round(n))} %"
    return f"{n:g} %"


def _mult(value: float) -> str:
    v = float(value)
    delta = (v - 1.0) * 100
    if abs(delta) < 0.05:
        return f"×{v:g}"
    sign = "+" if delta > 0 else ""
    shown = int(round(delta)) if abs(delta - round(delta)) < 0.05 else f"{delta:g}"
    return f"×{v:g} ({sign}{shown} %)"


def _tag(key: str) -> str:
    return TAG_LABELS.get(key, key.replace("_", " "))


def _format_scalar(key: str, value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "oui" if value else None
    if key in {"restore_energy_pct", "max_energy_bonus_pct", "offseason_species_chance_bonus"}:
        try:
            return _pct(float(value))
        except (TypeError, ValueError):
            return str(value)
    if key == "walk_time_mult":
        try:
            return _mult(float(value))
        except (TypeError, ValueError):
            return str(value)
    if key == "duration_minutes":
        try:
            return f"{int(value)} min"
        except (TypeError, ValueError):
            return str(value)
    if key.endswith("_minutes"):
        try:
            return f"{int(value)} min"
        except (TypeError, ValueError):
            return str(value)
    if key.endswith("_bonus") or key.endswith("_value") or key.endswith("_score"):
        return f"+{value}" if isinstance(value, (int, float)) and value > 0 else str(value)
    if isinstance(value, float) and 0 < value < 1 and key.endswith("_pct"):
        return _pct(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if abs(float(value) - round(float(value))) < 1e-9:
            return str(int(round(value)))
        return f"{value:g}"
    return str(value)


def _effect_lines(effects: dict[str, Any], *, markdown: bool) -> list[str]:
    lines: list[str] = []
    for key, raw in (effects or {}).items():
        if raw is None:
            continue
        if key in {"special_dialogue_trigger", "npc_exchange", "diving_effect", "diving_escape_bonus"}:
            continue
        if key == "encounter_tag_multipliers" and isinstance(raw, dict):
            bits = []
            for tag, mult in raw.items():
                try:
                    bits.append(f"{_tag(str(tag))} {_mult(float(mult))}")
                except (TypeError, ValueError):
                    bits.append(f"{_tag(str(tag))} {mult}")
            if bits:
                lines.append(_line("Rencontres", ", ".join(bits), markdown=markdown))
            continue
        if key == "minigame" and isinstance(raw, dict):
            bits = []
            for mk, mv in raw.items():
                label = MINIGAME_LABELS.get(str(mk), str(mk).replace("_", " "))
                try:
                    bits.append(f"{label} {_mult(float(mv))}")
                except (TypeError, ValueError):
                    bits.append(f"{label} {mv}")
            if bits:
                lines.append(_line("Mini-jeu", ", ".join(bits), markdown=markdown))
            continue
        formatted = _format_scalar(key, raw)
        if not formatted:
            continue
        label = EFFECT_LABELS.get(key, key.replace("_", " "))
        lines.append(_line(label[:1].upper() + label[1:], formatted, markdown=markdown))
    return lines


def inspect_item_lines(
    catalog: Catalog,
    item: Item,
    *,
    remaining: int | None = None,
    markdown: bool = True,
    heading: bool = True,
) -> list[str]:
    """Lignes de fiche item (stats, prix, effets)."""
    lines: list[str] = []
    if heading:
        if markdown:
            from common.display import item_display

            lines.append(item_display(catalog, item.key, brackets=True))
        else:
            lines.append(f"{item.key} = {item.name}")
    cat_label = CATEGORY_LABELS.get(item.category, item.category)
    lines.append(_line("Catégorie", cat_label, markdown=markdown))
    desc = (item.description or "").strip()
    if desc:
        lines.append(f"*{desc}*" if markdown else desc)
    lore = (item.lore or "").strip()
    if lore:
        lines.append(f"*{lore}*" if markdown else lore)
    eq = item.equipment
    if eq is not None and eq.equippable:
        slot = SLOT_LABELS.get(eq.slot or "", eq.slot or "—")
        lines.append(_line("Équipement", slot, markdown=markdown))
        if eq.capture_method:
            cap = CAPTURE_LABELS.get(eq.capture_method, eq.capture_method)
            lines.append(_line("Capture", cap, markdown=markdown))
        if eq.tool_profile:
            lines.append(_line("Profil", eq.tool_profile, markdown=markdown))
    dur = item.durability
    if dur is not None:
        if dur.max_days is not None or dur.unit == "days":
            cap = dur.max_days
            if remaining is not None and cap is not None:
                lines.append(_line("Durabilité", f"{remaining}/{cap} j", markdown=markdown))
            elif cap is not None:
                lines.append(_line("Durabilité", f"{cap} j", markdown=markdown))
        elif dur.max is not None:
            if remaining is not None:
                lines.append(
                    _line("Durabilité", f"{remaining}/{dur.max} usages", markdown=markdown)
                )
            else:
                lines.append(_line("Durabilité", f"{dur.max} usages", markdown=markdown))
        if dur.repairable and dur.repair_cost is not None:
            lines.append(
                _line(
                    "Réparation",
                    format_money(int(dur.repair_cost), catalog.game.money),
                    markdown=markdown,
                )
            )
    lines.extend(_effect_lines(item.effects or {}, markdown=markdown))
    col = item.collection
    if col is not None and col.collectible:
        group = COLLECTION_LABELS.get(col.group or "", col.group or "collection")
        bit = group
        if col.prestige_value:
            bit += f" · prestige {col.prestige_value}"
        lines.append(_line("Collection", bit, markdown=markdown))
    buy = item.economy.buy_price
    sell = item.economy.sell_price
    if buy is not None:
        lines.append(
            _line("Achat", format_money(buy, catalog.game.money), markdown=markdown)
        )
    if sell is not None:
        lines.append(
            _line("Vente", format_money(sell, catalog.game.money), markdown=markdown)
        )
    return lines


def inspect_species_lines(
    catalog: Catalog,
    species: Species,
    *,
    specimen: CaughtSpecimen | None = None,
    markdown: bool = True,
    heading: bool = True,
) -> list[str]:
    """Lignes de fiche espèce / spécimen."""
    lines: list[str] = []
    if heading:
        if markdown:
            from common.display import species_display

            extra = ""
            if specimen is not None:
                extra = f" · `{specimen.length_cm:g} cm` · `{specimen.weight_kg:g} kg`"
            lines.append(species_display(catalog, species.key, extra=extra, brackets=True))
        else:
            head = f"{species.key} = {species.name}"
            if specimen is not None:
                head += f" · {specimen.length_cm:g} cm · {specimen.weight_kg:g} kg"
            lines.append(head)
    rarity = RARITY_LABELS.get(species.rarity, species.rarity)
    try:
        env_name = catalog.get_milieu(species.environment).name
    except Exception:
        env_name = species.environment
    lines.append(_line("Rareté", rarity, markdown=markdown))
    lines.append(_line("Milieu", env_name, markdown=markdown))
    desc = (species.description or "").strip()
    if desc:
        lines.append(f"*{desc}*" if markdown else desc)
    bio = species.biology
    size_bits: list[str] = []
    if bio.min_length_cm is not None and bio.max_length_cm is not None:
        size_bits.append(f"{bio.min_length_cm:g}–{bio.max_length_cm:g} cm")
    if bio.min_weight_kg is not None and bio.max_weight_kg is not None:
        size_bits.append(f"{bio.min_weight_kg:g}–{bio.max_weight_kg:g} kg")
    if size_bits:
        lines.append(_line("Taille", " · ".join(size_bits), markdown=markdown))
    cap = species.capture
    cap_bits = [CAPTURE_LABELS.get(cap.method, cap.method)]
    if cap.difficulty:
        cap_bits.append(f"difficulté {cap.difficulty}")
    lines.append(_line("Capture", " · ".join(cap_bits), markdown=markdown))
    av = species.availability
    if av.seasons:
        lines.append(
            _line(
                "Saisons",
                ", ".join(SEASON_LABELS.get(s, s) for s in av.seasons),
                markdown=markdown,
            )
        )
    if av.time:
        lines.append(
            _line(
                "Moment",
                ", ".join(TIME_LABELS.get(t, t) for t in av.time),
                markdown=markdown,
            )
        )
    weather_bits: list[str] = []
    if av.weather_preferred:
        weather_bits.append("préfère " + ", ".join(av.weather_preferred))
    if av.weather_avoided:
        weather_bits.append("évite " + ", ".join(av.weather_avoided))
    if av.weather_required:
        weather_bits.append("exige " + ", ".join(av.weather_required))
    if weather_bits:
        lines.append(_line("Météo", " · ".join(weather_bits), markdown=markdown))
    if species.economy.sellable and species.economy.base_price is not None:
        lines.append(
            _line(
                "Prix de base",
                format_money(int(species.economy.base_price), catalog.game.money),
                markdown=markdown,
            )
        )
    elif not species.economy.sellable:
        lines.append(_line("Vente", "non vendable", markdown=markdown))
    if species.tags:
        lines.append(
            _line("Tags", ", ".join(_tag(t) for t in species.tags), markdown=markdown)
        )
    return lines


def inspect_item_text(catalog: Catalog, item: Item, **kwargs: Any) -> str:
    return "\n".join(inspect_item_lines(catalog, item, **kwargs))


def inspect_species_text(catalog: Catalog, species: Species, **kwargs: Any) -> str:
    return "\n".join(inspect_species_lines(catalog, species, **kwargs))


def inspect_dossier_plain(
    catalog: Catalog,
    key: str,
    *,
    remaining: int | None = None,
    specimen: CaughtSpecimen | None = None,
) -> str:
    """Version texte pour GPT : stats exactes, sans emoji."""
    try:
        item = catalog.get_item(key)
        return inspect_item_text(
            catalog, item, remaining=remaining, markdown=False, heading=True
        )
    except Exception:
        pass
    try:
        species = catalog.get_species(key)
        return inspect_species_text(
            catalog, species, specimen=specimen, markdown=False, heading=True
        )
    except Exception:
        return key
