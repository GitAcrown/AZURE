"""Village AZURE — présence déterministe, prix, visages."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from common.catalog import Catalog, Item, Npc, Species
from common.fishing.engine import item_is_gem
from common.player.models import CaughtSpecimen, PlayerSnapshot
from common.world import time_of_day_at, weather_bucket

ROLE_LABELS = {
    "shop": "Étal",
    "repair": "Atelier",
    "travel": "Passage",
    "special": "Eaux",
    "summon": "Collection",
    "lore": "Archives",
}


def npc_display_name(npc: Npc | None) -> str:
    if npc is None:
        return ""
    return str(npc.name or npc.key or "").strip()


def npc_role_label(npc: Npc) -> str:
    if npc.role == "shop" and npc.shop_mode == "buy":
        return "Achats"
    if npc.role == "shop" and npc.shop_mode == "sell":
        return "Étal"
    return ROLE_LABELS.get(npc.role or "", npc.role or "—")

SHOP_TAB_LABELS = {
    "buy": "Acheter",
    "sell": "Vendre",
}


@dataclass(frozen=True)
class VillageAnnouncement:
    id: int
    guild_id: int
    npc_key: str
    text: str
    modifier: dict[str, Any] = field(default_factory=dict)
    starts_at: str = ""
    ends_at: str = ""


def _pick_one(keys: list[str], seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return keys[int.from_bytes(digest[:8], "big") % len(keys)]


SAME_ROLE_MAX = 2


def _pick_n(keys: list[str], seed: str, n: int = SAME_ROLE_MAX) -> list[str]:
    """Tirage déterministe sans remise. Si le pool tient dans `n`, on les garde tous."""
    if n <= 0 or not keys:
        return []
    if len(keys) <= n:
        return list(keys)
    remaining = list(keys)
    chosen: list[str] = []
    i = 0
    while remaining and len(chosen) < n:
        key = _pick_one(remaining, f"{seed}:{i}")
        chosen.append(key)
        remaining.remove(key)
        i += 1
    order = {key: idx for idx, key in enumerate(keys)}
    chosen.sort(key=lambda key: order[key])
    return chosen


def skull_score(catalog: Catalog, snap: PlayerSnapshot) -> int:
    qty = {s.item_key: s.quantity for s in snap.stacks}
    total = 0
    for item in catalog.items:
        raw = (item.effects or {}).get("skeleton_summon_value")
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        total += value * int(qty.get(item.key, 0))
    return total


def clamp_environment_score(catalog: Catalog, env_score: int) -> int:
    hi = max(1, int(catalog.game.village.environment_score_max))
    return max(0, min(hi, int(env_score)))


def environment_pct(catalog: Catalog, env_score: int) -> int:
    hi = max(1, int(catalog.game.village.environment_score_max))
    return round(100 * clamp_environment_score(catalog, env_score) / hi)


def environment_is_good(catalog: Catalog, env_score: int) -> bool:
    return env_score >= catalog.game.village.environment_good_threshold


def environment_is_great(catalog: Catalog, env_score: int) -> bool:
    return environment_pct(catalog, env_score) > catalog.game.village.environment_great_threshold


def environment_is_poor(catalog: Catalog, env_score: int) -> bool:
    return environment_pct(catalog, env_score) < catalog.game.village.environment_poor_threshold


def env_quality_mult(catalog: Catalog, env_score: int | None) -> float:
    """Bonus / malus des raretés non communes selon la note environnementale."""
    if env_score is None:
        return 1.0
    if environment_is_great(catalog, env_score):
        return float(catalog.game.fishing.env_great_rarity_mult)
    if environment_is_poor(catalog, env_score):
        return float(catalog.game.fishing.env_poor_rarity_mult)
    return 1.0


def npc_portrait_filename(npc: Npc, *, env_good: bool) -> str:
    if npc.portraits.good or npc.portraits.bad:
        return npc.portrait_file(good=env_good)
    return npc.portraits.default


def village_bucket(catalog: Catalog, dt: datetime | None = None) -> int:
    return weather_bucket(dt or datetime.now(timezone.utc), catalog.game.world)


def present_npcs(
    catalog: Catalog,
    guild_id: int,
    *,
    skulls: int = 0,
    dt: datetime | None = None,
    bucket: int | None = None,
) -> list[Npc]:
    """Roster : jusqu'à 2 par fonction le jour, 1 la nuit. Gaia et Esmer toujours, Oz si seuil."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if bucket is None:
        bucket = weather_bucket(dt, catalog.game.world)
    tod = time_of_day_at(dt, catalog.game.world)
    cap = 1 if tod == "night" else SAME_ROLE_MAX
    present: list[Npc] = []

    def _add(candidates: list[Npc], seed: str, *, n: int = cap) -> None:
        for key in _pick_n([npc.key for npc in candidates], seed, n):
            present.append(catalog.get_npc(key))

    _add(catalog.npcs_by_shop_mode("sell"), f"{guild_id}:shop_sell:{bucket}")
    _add(catalog.npcs_by_shop_mode("buy"), f"{guild_id}:shop_buy:{bucket}")
    _add(catalog.npcs_by_role("repair"), f"{guild_id}:repair:{bucket}")
    _add(catalog.npcs_by_role("travel"), f"{guild_id}:travel:{bucket}")
    _add(catalog.npcs_by_role("special"), f"{guild_id}:special:{bucket}")
    _add(catalog.npcs_by_role("lore"), f"{guild_id}:lore:{bucket}", n=1)
    threshold = catalog.game.village.skull_summon_threshold
    if skulls >= threshold:
        _add(catalog.npcs_by_role("summon"), f"{guild_id}:summon:{bucket}")
    return present


def pick_announcer(present: list[Npc], guild_id: int, bucket: int) -> Npc:
    if not present:
        raise ValueError("aucun villageois présent")
    key = _pick_one([n.key for n in present], f"{guild_id}:announce:{bucket}")
    return next(n for n in present if n.key == key)


def cleanup_waste_items(catalog: Catalog) -> list[Item]:
    """Déchets revendables (prix + note environnementale)."""
    return [
        it
        for it in catalog.items
        if it.enabled
        and it.category == "waste"
        and it.economy.sell_price is not None
    ]


def waste_env_points(item: Item) -> int:
    raw = (item.effects or {}).get("environment_cleanup_score")
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def waste_sell_unit(item: Item, modifiers: list[dict] | None = None) -> int:
    unit = int(item.economy.sell_price or 0)
    return apply_named_mult(unit, modifiers or [], "waste_mult")


def shop_stock(catalog: Catalog, npc: Npc | None = None) -> list[Item]:
    """Rayon d'un vendeur. Sans PNJ : union des stocks `shop_mode: sell`."""
    if npc is not None:
        keys = list(npc.stock) if npc.shop_mode == "sell" else []
    else:
        keys = []
        for seller in catalog.npcs_by_shop_mode("sell"):
            keys.extend(seller.stock)
    out: list[Item] = []
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            continue
        try:
            item = catalog.get_item(key)
        except Exception:
            continue
        if not item.enabled or item.economy.buy_price is None:
            continue
        seen.add(key)
        out.append(item)
    return out


def talk_select_description(
    *,
    length_cm: float | None = None,
    weight_kg: float | None = None,
    qty: int = 1,
    price_plain: str = "",
    extra: str = "",
) -> str:
    """Description du select Parler : taille/poids toujours, prix seulement s'il est fourni."""
    bits: list[str] = []
    if length_cm is not None and weight_kg is not None:
        bits.append(f"{length_cm:g} cm · {weight_kg:g} kg")
    elif qty > 1:
        bits.append(f"×{qty}")
    if extra:
        bits.append(extra)
    if price_plain:
        bits.append(price_plain)
    return " · ".join(bits)


def talk_show_keys(
    catalog: Catalog,
    npc: Npc,
    *,
    snap: PlayerSnapshot | None = None,
    specimens: list[CaughtSpecimen] | None = None,
) -> list[str]:
    """Items ou espèces à montrer dans le modal, selon le PNJ. Vide = pas de select."""
    role = npc.role or ""
    keys: list[str] = []
    seen: set[str] = set()

    def _add(key: str) -> None:
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    if role == "shop" and npc.shop_mode == "sell":
        for item in shop_stock(catalog, npc):
            _add(item.key)
    elif role == "shop" and npc.shop_mode == "buy":
        for spec in specimens or []:
            try:
                species = catalog.get_species(spec.species_key)
            except Exception:
                continue
            if species.economy.sellable:
                _add(species.key)
        if snap is not None:
            for stack in snap.stacks:
                try:
                    item = catalog.get_item(stack.item_key)
                except Exception:
                    continue
                if item.economy.sell_price is not None:
                    _add(item.key)
    elif role == "repair" and snap is not None:
        for gear in snap.gear:
            try:
                item = catalog.get_item(gear.item_key)
            except Exception:
                continue
            dur = item.durability
            if dur is not None and dur.repairable:
                _add(item.key)
    elif role == "special" and snap is not None:
        for stack in snap.stacks:
            try:
                item = catalog.get_item(stack.item_key)
            except Exception:
                continue
            if item.category == "waste":
                _add(item.key)
    elif role == "summon" and snap is not None:
        if "fossil_in_stone" in snap.owned_keys():
            _add("fossil_in_stone")
    elif role == "lore":
        if snap is not None:
            for gear in snap.gear:
                _add(gear.item_key)
            gems: list[str] = []
            other: list[str] = []
            for stack in snap.stacks:
                try:
                    item = catalog.get_item(stack.item_key)
                except Exception:
                    continue
                if item_is_gem(item):
                    gems.append(item.key)
                else:
                    other.append(item.key)
            for key in gems + other:
                _add(key)
        for spec in specimens or []:
            _add(spec.species_key)
    return keys[:25]


DISPLAY_MODES = frozenset(
    {"none", "stock", "purse", "destinations", "repairs", "fossils", "env", "inspect"}
)


BOARD_KEYS_MAX = 4


def role_display(npc: Npc) -> str:
    """Panneau par défaut du rôle, seulement si on a quelque chose à montrer."""
    role = npc.role or ""
    if role == "shop" and npc.shop_mode == "sell":
        return "stock"
    if role == "shop" and npc.shop_mode == "buy":
        return "purse"
    if role == "repair":
        return "repairs"
    if role == "travel":
        return "destinations"
    if role == "special":
        return "env"
    if role == "summon":
        return "fossils"
    if role == "lore":
        return "inspect"
    return "none"


def focus_talk_board(
    npc: Npc,
    *,
    display: str,
    board_keys: list[str] | None,
    item_key: str | None = None,
    milieu_key: str | None = None,
    shown_key: str | None = None,
) -> tuple[str, list[str]]:
    """Ne garde que ce dont on parle / ce qu'on montre. Jamais le catalogue entier."""
    keys: list[str] = []
    for token in list(board_keys or []) + [shown_key, item_key, milieu_key]:
        if token and token not in keys:
            keys.append(token)
    keys = keys[:BOARD_KEYS_MAX]
    mode = display if display and display != "none" else "none"
    if mode == "none" and keys:
        mode = role_display(npc)
    return mode, keys


def allowed_displays(npc: Npc) -> set[str]:
    role = npc.role or ""
    if role == "shop" and npc.shop_mode == "sell":
        return {"none", "stock"}
    if role == "shop" and npc.shop_mode == "buy":
        return {"none", "purse"}
    if role == "repair":
        return {"none", "repairs"}
    if role == "travel":
        return {"none", "destinations"}
    if role == "special":
        return {"none", "env"}
    if role == "summon":
        return {"none", "fossils"}
    if role == "lore":
        return {"none", "inspect"}
    return {"none"}


def allowed_intents(npc: Npc) -> set[str]:
    role = npc.role or ""
    if role == "shop" and npc.shop_mode == "sell":
        return {"none", "buy"}
    if role == "shop" and npc.shop_mode == "buy":
        return {"none", "sell", "cleanup"}
    if role == "repair":
        return {"none", "repair"}
    if role == "travel":
        return {"none", "travel"}
    if role == "special":
        return {"none", "cleanup"}
    if role == "summon":
        return {"none", "exchange"}
    return {"none"}


def _repair_cap(item: Item) -> int | None:
    dur = item.durability
    if dur is None:
        return None
    if dur.max_days is not None:
        return int(dur.max_days)
    if dur.max is not None:
        return int(dur.max)
    return None


def talk_intent_block(
    catalog: Catalog,
    npc: Npc | None,
    snap: PlayerSnapshot,
    specimens: list[CaughtSpecimen],
    announcements: list[VillageAnnouncement],
    *,
    intent: str,
    item_key: str | None,
    milieu_key: str | None,
    quantity: int = 1,
    bargain: dict[str, Any] | None = None,
) -> str | None:
    """Raison pour désactiver Confirmer, ou None si l'action est possible."""
    qty = max(1, int(quantity))
    mods = price_modifiers(announcements, bargain)
    who = npc_display_name(npc)
    if intent == "buy":
        if not item_key:
            return "Dis-lui ce que tu veux lui acheter"
        try:
            item = catalog.get_item(item_key)
        except Exception:
            return "Cet article n'existe pas"
        if item.economy.buy_price is None:
            return f"{who} ne le vend pas" if who else "Pas en vente ici"
        stock = {it.key for it in shop_stock(catalog, npc)}
        if item.key not in stock:
            return "Ce n'est pas à l'étal"
        unit = apply_named_mult(int(item.economy.buy_price), mods, "buy_mult")
        if snap.money < unit * qty:
            return "Pas assez d'argent"
        inv = item.inventory
        if inv.stackable:
            owned = next((s.quantity for s in snap.stacks if s.item_key == item_key), 0)
            room = max(1, int(inv.max_stack)) - owned
            if room < qty:
                return "Pas de place dans le sac"
        return None
    if intent == "sell":
        if not item_key:
            return "Dis-lui ce que tu veux lui vendre"
        try:
            species = catalog.get_species(item_key)
        except Exception:
            species = None
        if species is not None:
            if not species.economy.sellable:
                return (
                    f"{who} n'achète pas cette prise"
                    if who
                    else "Cette prise ne s'achète pas ici"
                )
            have = sum(1 for s in specimens if s.species_key == item_key)
            if have < 1:
                return "Tu n'as pas cette prise"
            if have < qty:
                return f"Tu n'en as que {have}"
            return None
        try:
            item = catalog.get_item(item_key)
        except Exception:
            return "Rien à lui vendre"
        if item.economy.sell_price is None:
            return f"{who} n'achète pas ça" if who else "Ça ne s'achète pas ici"
        stack_qty = next((s.quantity for s in snap.stacks if s.item_key == item_key), 0)
        gear_n = sum(1 for g in snap.gear if g.item_key == item_key)
        if stack_qty >= qty:
            return None
        if gear_n >= 1 and qty == 1:
            return None
        if stack_qty + gear_n < 1:
            return "Tu n'as pas ça sur toi"
        return f"Tu n'en as que {stack_qty or gear_n}"
    if intent == "travel":
        if not milieu_key:
            return "Dis-lui où tu veux aller"
        if snap.milieu_key == milieu_key:
            return "Tu es déjà là"
        remaining = None
        if snap.travel_dest == milieu_key:
            remaining = travel_remaining_s(snap.travel_arrives_at)
        cost = apply_named_mult(
            passeur_price(catalog, remaining_s=remaining, snap=snap),
            mods,
            "travel_mult",
        )
        if cost > 0 and snap.money < cost:
            return "Pas assez d'argent"
        return None
    if intent == "repair":
        if not item_key:
            return "Dis-lui ce que tu veux faire réparer"
        gear = next((g for g in snap.gear if g.item_key == item_key), None)
        if gear is None:
            return "Tu n'as pas cet équipement sur toi"
        try:
            item = catalog.get_item(item_key)
        except Exception:
            return "Cet équipement n'existe pas"
        dur = item.durability
        if dur is None or not dur.repairable or dur.repair_cost is None:
            return f"{who} ne répare pas ça" if who else "Ça ne se répare pas ici"
        cap = _repair_cap(item)
        if cap is None or gear.durability is None or gear.durability >= cap:
            return "Déjà en bon état"
        cost = apply_named_mult(int(dur.repair_cost), mods, "repair_mult")
        if snap.money < cost:
            return "Pas assez d'argent"
        return None
    if intent == "exchange":
        if "fossil_in_stone" not in snap.owned_keys():
            return "Tu n'as pas de fossile à lui montrer"
        return None
    if intent == "cleanup":
        for stack in snap.stacks:
            try:
                item = catalog.get_item(stack.item_key)
            except Exception:
                continue
            if item.category != "waste":
                continue
            if item_key and item.key != item_key:
                continue
            if stack.quantity >= 1:
                return None
        return "Tu n'as pas de déchet à lui donner"
    return "Rien à confirmer pour l'instant"


def fossil_replicas(catalog: Catalog) -> list[Item]:
    return [
        it
        for it in catalog.items
        if it.enabled
        and it.collection is not None
        and it.collection.collectible
        and it.collection.group == "fossil_replicas"
    ]


def _ratio(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.5
    return (value - lo) / (hi - lo)


def specimen_base_price(
    catalog: Catalog, species: Species, length_cm: float, weight_kg: float
) -> int:
    """Prix 50 %–150 % de `base_price` selon taille et poids."""
    bio = species.biology
    settings = catalog.game.fishing.specimen
    if bio.min_length_cm is not None and bio.max_length_cm is not None:
        lo_l, hi_l = float(bio.min_length_cm), float(bio.max_length_cm)
    else:
        lo_l, hi_l = float(settings.fallback_length_cm[0]), float(settings.fallback_length_cm[1])
    if bio.min_weight_kg is not None and bio.max_weight_kg is not None:
        lo_w, hi_w = float(bio.min_weight_kg), float(bio.max_weight_kg)
    else:
        lo_w, hi_w = float(settings.fallback_weight_kg[0]), float(settings.fallback_weight_kg[1])
    t = (_ratio(length_cm, lo_l, hi_l) + _ratio(weight_kg, lo_w, hi_w)) / 2.0
    t = min(1.0, max(0.0, t))
    base = int(species.economy.base_price or 0)
    return round(base * (0.5 + t))


ANNOUNCE_KINDS = {
    "sale_weight": "Vente ×1,3 · poissons dès 0,8 kg",
    "sale_length": "Vente ×1,25 · prises dès 35 cm",
    "sale_rarity": "Vente ×1,4 · prises peu communes+",
    "sale_ocean": "Vente ×1,2 · prises d'océan",
    "sale_river": "Vente ×1,2 · prises de rivière",
    "sale_pond": "Vente ×1,2 · prises d'étang",
    "shop_buy": "Boutique −20 %",
    "travel": "Passage −50 %",
    "repair": "Réparations −30 %",
    "waste": "Déchets ×2",
}


def infer_modifier_kind(modifier: dict[str, Any]) -> str:
    kind = str(modifier.get("kind") or "").strip()
    if kind == "bargain":
        return "bargain"
    if kind in ANNOUNCE_KINDS:
        return kind
    if modifier.get("travel_mult") is not None:
        return "travel"
    if modifier.get("repair_mult") is not None:
        return "repair"
    if modifier.get("buy_mult") is not None:
        return "shop_buy"
    if modifier.get("waste_mult") is not None:
        return "waste"
    if modifier.get("rarity"):
        return "sale_rarity"
    milieu = modifier.get("milieu")
    if milieu == "ocean":
        return "sale_ocean"
    if milieu == "river":
        return "sale_river"
    if milieu == "pond":
        return "sale_pond"
    if modifier.get("min_length_cm") is not None:
        return "sale_length"
    if modifier.get("mult") is not None or modifier.get("min_weight_kg") is not None:
        return "sale_weight"
    return ""


def _fmt_factor(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "?"
    if number == int(number):
        return str(int(number))
    return str(number).replace(".", ",")


def _fmt_off(value: Any) -> str:
    try:
        pct = round((1.0 - float(value)) * 100)
    except (TypeError, ValueError):
        return "?"
    if pct > 0:
        return f"−{pct} %"
    if pct < 0:
        return f"+{abs(pct)} %"
    return "prix inchangé"


def modifier_label(modifier: dict[str, Any]) -> str:
    kind = infer_modifier_kind(modifier)
    if kind == "sale_weight":
        return (
            f"vente ×{_fmt_factor(modifier.get('mult', 1.3))} "
            f"dès {modifier.get('min_weight_kg', 0.8)} kg"
        )
    if kind == "sale_length":
        return (
            f"vente ×{_fmt_factor(modifier.get('mult', 1.25))} "
            f"dès {modifier.get('min_length_cm', 35)} cm"
        )
    if kind == "sale_rarity":
        return f"vente ×{_fmt_factor(modifier.get('mult', 1.4))} · peu communes+"
    if kind == "sale_ocean":
        return f"vente ×{_fmt_factor(modifier.get('mult', 1.2))} · océan"
    if kind == "sale_river":
        return f"vente ×{_fmt_factor(modifier.get('mult', 1.2))} · rivière"
    if kind == "sale_pond":
        return f"vente ×{_fmt_factor(modifier.get('mult', 1.2))} · étang"
    if kind == "shop_buy":
        return f"boutique {_fmt_off(modifier.get('buy_mult', 0.8))}"
    if kind == "travel":
        return f"passage {_fmt_off(modifier.get('travel_mult', 0.5))}"
    if kind == "repair":
        return f"réparations {_fmt_off(modifier.get('repair_mult', 0.7))}"
    if kind == "waste":
        return f"déchets ×{_fmt_factor(modifier.get('waste_mult', 2.0))}"
    if kind == "bargain":
        if modifier.get("buy_mult") is not None:
            return f"négociation {_fmt_off(modifier.get('buy_mult'))}"
        if modifier.get("travel_mult") is not None:
            return f"négociation {_fmt_off(modifier.get('travel_mult'))}"
        if modifier.get("repair_mult") is not None:
            return f"négociation {_fmt_off(modifier.get('repair_mult'))}"
        if modifier.get("waste_mult") is not None:
            return f"négociation ×{_fmt_factor(modifier.get('waste_mult'))}"
        if modifier.get("mult") is not None or modifier.get("sell_mult") is not None:
            factor = modifier.get("mult", modifier.get("sell_mult"))
            return f"négociation ×{_fmt_factor(factor)}"
        return "négociation"
    return ANNOUNCE_KINDS.get(kind, "")


def announcement_remaining_label(ends_at: str, now: datetime | None = None) -> str:
    try:
        dt = datetime.fromisoformat(ends_at)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    secs = (dt - now).total_seconds()
    if secs <= 0:
        return "fini"
    if secs < 3600:
        mins = max(1, round(secs / 60.0))
        return f"encore {mins} min"
    hours = max(1, round(secs / 3600.0))
    return f"encore {hours} h"


def build_announcement_modifier(kind: str) -> dict[str, Any]:
    if kind == "sale_weight":
        return {"kind": kind, "min_weight_kg": 0.8, "mult": 1.3}
    if kind == "sale_length":
        return {"kind": kind, "min_length_cm": 35, "mult": 1.25}
    if kind == "sale_rarity":
        return {"kind": kind, "rarity": "uncommon", "mult": 1.4}
    if kind == "sale_ocean":
        return {"kind": kind, "milieu": "ocean", "mult": 1.2}
    if kind == "sale_river":
        return {"kind": kind, "milieu": "river", "mult": 1.2}
    if kind == "sale_pond":
        return {"kind": kind, "milieu": "pond", "mult": 1.2}
    if kind == "shop_buy":
        return {"kind": kind, "buy_mult": 0.8}
    if kind == "travel":
        return {"kind": kind, "travel_mult": 0.5}
    if kind == "repair":
        return {"kind": kind, "repair_mult": 0.7}
    if kind == "waste":
        return {"kind": kind, "waste_mult": 2.0}
    return {}


def _scale_price(price: int, factor: Any) -> int:
    try:
        return max(0, round(price * float(factor)))
    except (TypeError, ValueError):
        return price


def apply_named_mult(price: int, modifiers: list[dict[str, Any]], key: str) -> int:
    out = price
    for modifier in modifiers:
        raw = modifier.get(key)
        if raw is None:
            continue
        out = _scale_price(out, raw)
    return out


def modifier_matches_specimen(
    modifier: dict[str, Any],
    species: Species,
    *,
    length_cm: float,
    weight_kg: float,
) -> bool:
    min_w = modifier.get("min_weight_kg")
    if min_w is not None and weight_kg < float(min_w):
        return False
    min_l = modifier.get("min_length_cm")
    if min_l is not None and length_cm < float(min_l):
        return False
    keys = modifier.get("species")
    if keys:
        allowed = {str(k) for k in keys}
        if species.key not in allowed:
            return False
    rarity = modifier.get("rarity")
    if rarity and species.rarity != str(rarity):
        return False
    milieu = modifier.get("milieu")
    if milieu and species.environment != str(milieu):
        return False
    kind = infer_modifier_kind(modifier)
    if kind in {"shop_buy", "travel", "repair", "waste"}:
        return False
    return True


def apply_sale_modifiers(
    price: int,
    modifiers: list[dict[str, Any]],
    *,
    species: Species,
    length_cm: float,
    weight_kg: float,
) -> int:
    out = price
    for modifier in modifiers:
        if not modifier_matches_specimen(
            modifier, species, length_cm=length_cm, weight_kg=weight_kg
        ):
            continue
        raw = modifier.get("mult")
        if raw is None:
            continue
        out = _scale_price(out, raw)
    return max(0, out)


def specimen_price(
    catalog: Catalog,
    species: Species,
    length_cm: float,
    weight_kg: float,
    *,
    modifiers: Optional[list[dict[str, Any]]] = None,
) -> int:
    price = specimen_base_price(catalog, species, length_cm, weight_kg)
    if modifiers:
        price = apply_sale_modifiers(
            price,
            modifiers,
            species=species,
            length_cm=length_cm,
            weight_kg=weight_kg,
        )
    return price


def announcement_modifiers(announcements: list[VillageAnnouncement]) -> list[dict[str, Any]]:
    return [a.modifier for a in announcements if a.modifier]


def price_modifiers(
    announcements: list[VillageAnnouncement] | None = None,
    bargain: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    mods = announcement_modifiers(announcements or [])
    if bargain:
        return [*mods, bargain]
    return mods


def npc_can_bargain(npc: Npc) -> bool:
    role = npc.role or ""
    if role == "shop":
        return True
    return role in {"repair", "travel", "special"}


def bargain_modifier(catalog: Catalog, npc: Npc) -> dict[str, Any]:
    cfg = catalog.game.village.bargain
    mod: dict[str, Any] = {"kind": "bargain"}
    role = npc.role or ""
    if role == "shop" and npc.shop_mode == "sell":
        mod["buy_mult"] = float(cfg.buy_mult)
    elif role == "shop" and npc.shop_mode == "buy":
        mod["mult"] = float(cfg.sell_mult)
        mod["sell_mult"] = float(cfg.sell_mult)
        mod["waste_mult"] = float(cfg.waste_mult)
    elif role == "travel":
        mod["travel_mult"] = float(cfg.travel_mult)
    elif role == "repair":
        mod["repair_mult"] = float(cfg.repair_mult)
    elif role == "special":
        mod["waste_mult"] = float(cfg.waste_mult)
        mod["sell_mult"] = float(cfg.sell_mult)
    return mod


def walk_time_mult(catalog: Catalog, snap: PlayerSnapshot | None = None) -> float:
    """1.0 par défaut. Boussole équipée : `walk_time_mult` (0.2 = −80 %)."""
    if snap is None:
        return 1.0
    eq = snap.equipped.get("objet")
    if eq is None:
        return 1.0
    key = eq.gear.item_key if eq.gear is not None else eq.item_key
    if not key:
        return 1.0
    try:
        item = catalog.get_item(key)
    except Exception:
        return 1.0
    raw = (item.effects or {}).get("walk_time_mult")
    if raw is None:
        return 1.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return min(1.0, max(0.05, value))


def travel_duration_s(
    catalog: Catalog,
    *,
    walk_mult: float | None = None,
    snap: PlayerSnapshot | None = None,
) -> int:
    if walk_mult is None:
        walk_mult = walk_time_mult(catalog, snap)
    base = max(60, int(catalog.game.village.travel_minutes) * 60)
    try:
        mult = float(walk_mult)
    except (TypeError, ValueError):
        mult = 1.0
    return max(60, int(round(base * min(1.0, max(0.05, mult)))))


def walk_minutes(
    catalog: Catalog, snap: PlayerSnapshot | None = None, *, walk_mult: float | None = None
) -> int:
    return max(1, travel_duration_s(catalog, walk_mult=walk_mult, snap=snap) // 60)


def travel_remaining_s(arrives_at: str | None, now: datetime | None = None) -> float | None:
    if not arrives_at:
        return None
    try:
        dt = datetime.fromisoformat(arrives_at)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (dt - now).total_seconds()


def travel_minutes_left(remaining_s: float) -> int:
    if remaining_s <= 0:
        return 0
    return max(1, round(remaining_s / 60.0))


def passeur_price(
    catalog: Catalog,
    *,
    remaining_s: float | None,
    snap: PlayerSnapshot | None = None,
    walk_mult: float | None = None,
) -> int:
    """Prix du raccourci : plein tarif, ou au prorata du temps restant."""
    full = max(0, int(catalog.game.village.travel_cost))
    total = float(travel_duration_s(catalog, walk_mult=walk_mult, snap=snap))
    if remaining_s is None:
        return full
    remaining_s = max(0.0, float(remaining_s))
    if remaining_s <= 0 or full <= 0:
        return 0
    return max(1, round(full * min(1.0, remaining_s / total)))
