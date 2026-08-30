"""Village AZURE — présence déterministe, prix, visages."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from common.catalog import Catalog, Item, Npc, Species
from common.player.models import CaughtSpecimen, PlayerSnapshot
from common.world import weather_bucket

ROLE_LABELS = {
    "shop": "Marchand",
    "repair": "Réparateur",
    "travel": "Passeur",
    "special": "Gardienne",
    "summon": "Collectionneur",
}


def npc_role_label(npc: Npc) -> str:
    if npc.role == "shop" and npc.shop_mode == "buy":
        return "Acheteur"
    if npc.role == "shop" and npc.shop_mode == "sell":
        return "Marchand"
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


def environment_is_good(catalog: Catalog, env_score: int) -> bool:
    return env_score >= catalog.game.village.environment_good_threshold


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
    """Roster : 1 vendeur, 1 acheteur, 1 repair, 1 travel, Gaia, Oz si seuil."""
    if bucket is None:
        bucket = weather_bucket(dt, catalog.game.world)
    present: list[Npc] = []
    sellers = catalog.npcs_by_shop_mode("sell")
    if sellers:
        key = _pick_one([n.key for n in sellers], f"{guild_id}:shop_sell:{bucket}")
        present.append(catalog.get_npc(key))
    buyers = catalog.npcs_by_shop_mode("buy")
    if buyers:
        key = _pick_one([n.key for n in buyers], f"{guild_id}:shop_buy:{bucket}")
        present.append(catalog.get_npc(key))
    repairs = catalog.npcs_by_role("repair")
    if repairs:
        key = _pick_one([n.key for n in repairs], f"{guild_id}:repair:{bucket}")
        present.append(catalog.get_npc(key))
    travels = catalog.npcs_by_role("travel")
    if travels:
        key = _pick_one([n.key for n in travels], f"{guild_id}:travel:{bucket}")
        present.append(catalog.get_npc(key))
    for special in catalog.npcs_by_role("special"):
        present.append(special)
    threshold = catalog.game.village.skull_summon_threshold
    if skulls >= threshold:
        present.extend(catalog.npcs_by_role("summon"))
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
    return keys[:25]


DISPLAY_MODES = frozenset(
    {"none", "stock", "purse", "destinations", "repairs", "fossils", "env"}
)


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
) -> str | None:
    """Raison pour désactiver Confirmer, ou None si l'action est possible."""
    qty = max(1, int(quantity))
    mods = announcement_modifiers(announcements)
    if intent == "buy":
        if not item_key:
            return "Dis-lui quoi acheter"
        try:
            item = catalog.get_item(item_key)
        except Exception:
            return "Cet item n'existe pas"
        if item.economy.buy_price is None:
            return "Pas en vente"
        stock = {it.key for it in shop_stock(catalog, npc)}
        if item.key not in stock:
            return "Pas en rayon"
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
            return "Dis-lui quoi vendre"
        try:
            species = catalog.get_species(item_key)
        except Exception:
            species = None
        if species is not None:
            if not species.economy.sellable:
                return "Cette prise ne se vend pas"
            have = sum(1 for s in specimens if s.species_key == item_key)
            if have < 1:
                return "Tu n'as pas cette prise"
            if have < qty:
                return f"Pas assez ({have})"
            return None
        try:
            item = catalog.get_item(item_key)
        except Exception:
            return "Rien à vendre"
        if item.economy.sell_price is None:
            return "Ça ne se vend pas"
        stack_qty = next((s.quantity for s in snap.stacks if s.item_key == item_key), 0)
        gear_n = sum(1 for g in snap.gear if g.item_key == item_key)
        if stack_qty >= qty:
            return None
        if gear_n >= 1 and qty == 1:
            return None
        if stack_qty + gear_n < 1:
            return "Tu n'as pas ça"
        return f"Pas assez ({stack_qty or gear_n})"
    if intent == "travel":
        if not milieu_key:
            return "Dis-lui où aller"
        if snap.milieu_key == milieu_key:
            return "Tu es déjà là"
        remaining = None
        if snap.travel_dest == milieu_key:
            remaining = travel_remaining_s(snap.travel_arrives_at)
        cost = apply_named_mult(
            passeur_price(catalog, remaining_s=remaining), mods, "travel_mult"
        )
        if cost > 0 and snap.money < cost:
            return "Pas assez d'argent"
        return None
    if intent == "repair":
        if not item_key:
            return "Dis-lui quoi réparer"
        gear = next((g for g in snap.gear if g.item_key == item_key), None)
        if gear is None:
            return "Tu n'as pas cet équipement"
        try:
            item = catalog.get_item(item_key)
        except Exception:
            return "Équipement inconnu"
        dur = item.durability
        if dur is None or not dur.repairable or dur.repair_cost is None:
            return "Ça ne se répare pas"
        cap = _repair_cap(item)
        if cap is None or gear.durability is None or gear.durability >= cap:
            return "Déjà en bon état"
        cost = apply_named_mult(int(dur.repair_cost), mods, "repair_mult")
        if snap.money < cost:
            return "Pas assez d'argent"
        return None
    if intent == "exchange":
        if "fossil_in_stone" not in snap.owned_keys():
            return "Pas de fossile"
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
        return "Rien à ramasser"
    return "Rien à confirmer"


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


def travel_duration_s(catalog: Catalog) -> int:
    return max(60, int(catalog.game.village.travel_minutes) * 60)


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


def passeur_price(catalog: Catalog, *, remaining_s: float | None) -> int:
    """Prix du raccourci : plein tarif, ou au prorata du temps restant."""
    full = max(0, int(catalog.game.village.travel_cost))
    total = float(travel_duration_s(catalog))
    if remaining_s is None:
        return full
    remaining_s = max(0.0, float(remaining_s))
    if remaining_s <= 0 or full <= 0:
        return 0
    return max(1, round(full * remaining_s / total))
