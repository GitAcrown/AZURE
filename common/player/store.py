"""Persistance joueur AZURE (profil, inventaire, équipement)."""

from __future__ import annotations

import json
import logging
import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from common.catalog import Catalog, CatalogError, Item, Npc
from common.display import weather_display
from common.village import (
    VillageAnnouncement,
    apply_named_mult,
    bargain_modifier,
    clamp_environment_score,
    env_quality_mult,
    fossil_replicas,
    infer_modifier_kind,
    npc_can_bargain,
    passeur_price,
    price_modifiers,
    shop_stock,
    specimen_price,
    travel_duration_s,
    travel_remaining_s,
    village_bucket,
)
from common.world import weather_at
from common.fishing import (
    FishingError,
    Specimen,
    bite_timings,
    build_pool,
    context_from_world,
    generate_specimen,
    roll,
    roll_loot,
    roll_waste,
    cast_energy_parts,
    energy_shortfall_message,
)

from .db import ACTIVE_SLOTS, BAIT_SLOT, GEAR_SLOTS, connect_db
from .energy import (
    bonus_pct_at,
    coffee_minutes_left,
    effective_energy_max,
    parse_iso,
    regen_energy,
)
from .errors import PlayerError
from .models import (
    CaughtSpecimen,
    CastResult,
    DexRow,
    EquippedSlot,
    GearInstance,
    PendingCast,
    PlayerSnapshot,
    Stack,
    VillageTalkState,
)

logger = logging.getLogger("AZURE.Player")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_stackable(item: Item) -> bool:
    return bool(item.inventory.stackable)


def _max_durability(item: Item) -> int | None:
    dur = item.durability
    if dur is None:
        return None
    if dur.max_days is not None:
        return int(dur.max_days)
    if dur.max is not None:
        return int(dur.max)
    return None


def _specimen_better(length: float, weight: float, old_len, old_w) -> bool:
    """True si (longueur, puis poids) bat l'ancien record."""
    if old_len is None or old_w is None:
        return True
    old_len_f = float(old_len)
    old_w_f = float(old_w)
    if length != old_len_f:
        return length > old_len_f
    return weight > old_w_f


def _effect_bonus(item: Item, key: str) -> int:
    raw = (item.effects or {}).get(key)
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _gear_live(item: Item, durability: int | None) -> bool:
    if item.durability is None or durability is None:
        return True
    return durability > 0


def collect_owned_effects(
    catalog: Catalog,
    gear: list[GearInstance],
    stacks: list[Stack],
    equipped: dict[str, EquippedSlot] | None = None,
) -> dict[str, Any]:
    """Effets des pièces **équipées** uniquement (un objet passif à la fois)."""
    effects: dict[str, Any] = {}
    for eq in (equipped or {}).values():
        key = None
        durability = None
        if eq.gear is not None:
            key = eq.gear.item_key
            durability = eq.gear.durability
        elif eq.item_key:
            key = eq.item_key
        if not key:
            continue
        try:
            item = catalog.get_item(key)
        except CatalogError:
            continue
        if not _gear_live(item, durability):
            continue
        effects.update(item.effects or {})
    return effects


def carry_limits(
    catalog: Catalog,
    gear: list[GearInstance],
    stacks: list[Stack],
    equipped: dict[str, EquippedSlot] | None = None,
) -> tuple[int, int]:
    """Capacités : base YAML + bonus de l'objet équipé seulement."""
    player = catalog.game.player
    fish = player.fish_carry_capacity
    creature = player.non_fish_carry_capacity
    obj = (equipped or {}).get("objet")
    if obj is None:
        return fish, creature
    key = obj.gear.item_key if obj.gear is not None else obj.item_key
    durability = obj.gear.durability if obj.gear is not None else None
    if not key:
        return fish, creature
    try:
        item = catalog.get_item(key)
    except CatalogError:
        return fish, creature
    if not _gear_live(item, durability):
        return fish, creature
    fish += _effect_bonus(item, "fish_carry_capacity_bonus")
    creature += _effect_bonus(item, "non_fish_carry_capacity_bonus")
    return fish, creature


def carry_compartment(catalog: Catalog, species_key: str) -> str:
    """`fish` si fishdex, sinon `creature` (creaturedex, shelldex, inconnu)."""
    try:
        group = catalog.get_species(species_key).collection.group or ""
    except CatalogError:
        return "creature"
    return "fish" if group == "fishdex" else "creature"


class PlayerStore:
    def __init__(self, conn: aiosqlite.Connection, catalog: Catalog) -> None:
        self._conn = conn
        self.catalog = catalog

    async def close(self) -> None:
        await self._conn.close()

    async def get_or_create(self, guild_id: int, user_id: int) -> PlayerSnapshot:
        existing = await self._fetch_player_row(guild_id, user_id)
        if existing is not None:
            snap = await self.snapshot(guild_id, user_id)
            snap.created = False
            return snap

        defaults = self.catalog.game.player
        await self._conn.execute(
            """
            INSERT INTO players (
                guild_id, user_id, energy, energy_max, money, milieu_key,
                created_at, energy_updated_at, energy_bonus_pct, energy_bonus_until
            )
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?, 0, NULL)
            """,
            (
                guild_id,
                user_id,
                defaults.energy_start,
                defaults.energy_max,
                defaults.money_start,
                _now(),
                _now(),
            ),
        )
        await self._grant_starter(guild_id, user_id)
        await self._conn.commit()
        logger.info("Profil créé guild=%s user=%s", guild_id, user_id)
        snap = await self.snapshot(guild_id, user_id)
        snap.created = True
        return snap

    async def snapshot(self, guild_id: int, user_id: int) -> PlayerSnapshot:
        row, just_arrived = await self._tick_energy(guild_id, user_id)
        if row is None:
            raise PlayerError("profil introuvable")

        stacks: list[Stack] = []
        async with self._conn.execute(
            """
            SELECT item_key, quantity FROM inventory_stacks
            WHERE guild_id = ? AND user_id = ?
            ORDER BY item_key
            """,
            (guild_id, user_id),
        ) as cur:
            async for r in cur:
                stacks.append(Stack(item_key=r["item_key"], quantity=int(r["quantity"])))

        gear_by_id: dict[int, GearInstance] = {}
        gear: list[GearInstance] = []
        async with self._conn.execute(
            """
            SELECT id, item_key, durability FROM gear_instances
            WHERE guild_id = ? AND user_id = ?
            ORDER BY id
            """,
            (guild_id, user_id),
        ) as cur:
            async for r in cur:
                inst = GearInstance(
                    id=int(r["id"]),
                    item_key=r["item_key"],
                    durability=r["durability"] if r["durability"] is None else int(r["durability"]),
                )
                gear.append(inst)
                gear_by_id[inst.id] = inst

        equipped: dict[str, EquippedSlot] = {}
        async with self._conn.execute(
            """
            SELECT slot, gear_id, item_key FROM equipped
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ) as cur:
            async for r in cur:
                slot = r["slot"]
                gear_id = int(r["gear_id"]) if r["gear_id"] is not None else None
                equipped[slot] = EquippedSlot(
                    slot=slot,
                    gear_id=gear_id,
                    item_key=r["item_key"],
                    gear=gear_by_id.get(gear_id) if gear_id is not None else None,
                )

        now = datetime.now(timezone.utc)
        bonus_until = parse_iso(row["energy_bonus_until"])
        bonus = bonus_pct_at(float(row["energy_bonus_pct"] or 0), bonus_until, now)
        base_max = int(row["energy_max"])
        eff_max = effective_energy_max(base_max, bonus, bonus_until, now)
        dex_found = 0
        async with self._conn.execute(
            "SELECT COUNT(*) AS n FROM fishdex WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cur:
            dex_row = await cur.fetchone()
            if dex_row is not None:
                dex_found = int(dex_row["n"])
        dex_total = sum(1 for s in self.catalog.species if s.collection.collectible)
        fish_n, creature_n = await self._count_caught_by_compartment(guild_id, user_id)
        fish_max, creature_max = carry_limits(self.catalog, gear, stacks, equipped)
        return PlayerSnapshot(
            guild_id=guild_id,
            user_id=user_id,
            energy=int(row["energy"]),
            energy_max=eff_max,
            energy_max_base=base_max,
            money=int(row["money"]),
            milieu_key=row["milieu_key"],
            created_at=row["created_at"],
            stacks=stacks,
            gear=gear,
            equipped=equipped,
            created=False,
            coffee_minutes=coffee_minutes_left(bonus_until, now) if bonus else None,
            coffee_pct=bonus,
            dex_found=dex_found,
            dex_total=dex_total,
            fish_carry=fish_n,
            fish_carry_max=fish_max,
            creature_carry=creature_n,
            creature_carry_max=creature_max,
            travel_dest=row["travel_dest"],
            travel_arrives_at=row["travel_arrives_at"],
            just_arrived=just_arrived,
        )

    async def add_item(
        self,
        guild_id: int,
        user_id: int,
        item_key: str,
        quantity: int = 1,
        *,
        auto_equip: bool = False,
        commit: bool = True,
    ) -> int:
        """Ajoute un item. Renvoie la quantité effectivement ajoutée."""
        if quantity < 1:
            raise PlayerError("la quantité doit être ≥ 1")
        item = self._item(item_key)
        await self.get_or_create(guild_id, user_id)

        if _is_stackable(item):
            added = await self._add_stack(guild_id, user_id, item, quantity)
            if auto_equip:
                await self._try_auto_equip_stack(guild_id, user_id, item)
            if commit:
                await self._conn.commit()
            return added

        for _ in range(quantity):
            gear_id = await self._insert_gear(guild_id, user_id, item)
            if auto_equip:
                await self._try_auto_equip_gear(guild_id, user_id, item, gear_id)
        if commit:
            await self._conn.commit()
        return quantity

    async def add_money(self, guild_id: int, user_id: int, delta: int) -> int:
        await self.get_or_create(guild_id, user_id)
        snap = await self.snapshot(guild_id, user_id)
        new_value = max(0, snap.money + delta)
        await self._conn.execute(
            "UPDATE players SET money = ? WHERE guild_id = ? AND user_id = ?",
            (new_value, guild_id, user_id),
        )
        await self._conn.commit()
        return new_value

    async def set_energy(self, guild_id: int, user_id: int, value: int) -> int:
        await self.get_or_create(guild_id, user_id)
        snap = await self.snapshot(guild_id, user_id)
        new_value = max(0, min(snap.energy_max, value))
        await self._conn.execute(
            """
            UPDATE players SET energy = ?, energy_updated_at = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (new_value, _now(), guild_id, user_id),
        )
        await self._conn.commit()
        return new_value

    async def set_milieu(self, guild_id: int, user_id: int, milieu_key: str) -> tuple[bool, str]:
        """Marche gratuite. Premier milieu : instantané. Renvoie `(changé, dest)`."""
        try:
            milieu = self.catalog.get_milieu(milieu_key)
        except CatalogError as exc:
            raise PlayerError(f"milieu inconnu : {milieu_key!r}") from exc
        await self.get_or_create(guild_id, user_id)
        snap = await self.snapshot(guild_id, user_id)
        if snap.milieu_key == milieu.key:
            if snap.travel_dest:
                await self._conn.execute(
                    """
                    UPDATE players
                    SET travel_dest = NULL, travel_arrives_at = NULL
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (guild_id, user_id),
                )
                await self._conn.commit()
            return False, milieu.key
        if snap.travel_dest == milieu.key:
            return False, milieu.key
        if snap.milieu_key is None:
            await self._conn.execute(
                """
                UPDATE players
                SET milieu_key = ?, travel_dest = NULL, travel_arrives_at = NULL
                WHERE guild_id = ? AND user_id = ?
                """,
                (milieu.key, guild_id, user_id),
            )
            await self._conn.commit()
            return True, milieu.key
        arrives = datetime.now(timezone.utc) + timedelta(
            seconds=travel_duration_s(self.catalog, snap=snap)
        )
        await self._conn.execute(
            """
            UPDATE players
            SET travel_dest = ?, travel_arrives_at = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (milieu.key, arrives.isoformat(), guild_id, user_id),
        )
        await self._conn.commit()
        return True, milieu.key

    async def unequip(self, guild_id: int, user_id: int, slot: str) -> str:
        if slot not in ACTIVE_SLOTS:
            raise PlayerError(f"slot inconnu : {slot!r}")
        await self.get_or_create(guild_id, user_id)
        snap = await self.snapshot(guild_id, user_id)
        if slot not in snap.equipped:
            raise PlayerError("ce slot est déjà vide")
        await self._conn.execute(
            "DELETE FROM equipped WHERE guild_id = ? AND user_id = ? AND slot = ?",
            (guild_id, user_id, slot),
        )
        await self._conn.commit()
        return slot

    async def equip_gear(self, guild_id: int, user_id: int, gear_id: int) -> str:
        await self.get_or_create(guild_id, user_id)
        async with self._conn.execute(
            """
            SELECT id, item_key, durability FROM gear_instances
            WHERE id = ? AND guild_id = ? AND user_id = ?
            """,
            (gear_id, guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise PlayerError("équipement introuvable")
        item = self._item(row["item_key"])
        eq = item.equipment
        if eq is None or not eq.equippable or eq.slot not in GEAR_SLOTS:
            raise PlayerError("cet item ne s'équipe pas")
        slot = eq.slot
        assert slot is not None
        await self._conn.execute(
            """
            INSERT INTO equipped (guild_id, user_id, slot, gear_id, item_key)
            VALUES (?, ?, ?, ?, NULL)
            ON CONFLICT(guild_id, user_id, slot)
            DO UPDATE SET gear_id = excluded.gear_id, item_key = NULL
            """,
            (guild_id, user_id, slot, gear_id),
        )
        await self._conn.commit()
        return slot

    async def equip_bait(self, guild_id: int, user_id: int, item_key: str) -> str:
        item = self._item(item_key)
        eq = item.equipment
        if eq is None or not eq.equippable or eq.slot != BAIT_SLOT:
            raise PlayerError("cet item n'est pas un appât")
        await self.get_or_create(guild_id, user_id)
        qty = 0
        async with self._conn.execute(
            """
            SELECT quantity FROM inventory_stacks
            WHERE guild_id = ? AND user_id = ? AND item_key = ?
            """,
            (guild_id, user_id, item.key),
        ) as cur:
            stack = await cur.fetchone()
            if stack is not None:
                qty = int(stack["quantity"])
        if qty < 1:
            raise PlayerError("tu n'as pas cet appât")
        await self._conn.execute(
            """
            INSERT INTO equipped (guild_id, user_id, slot, gear_id, item_key)
            VALUES (?, ?, ?, NULL, ?)
            ON CONFLICT(guild_id, user_id, slot)
            DO UPDATE SET gear_id = NULL, item_key = excluded.item_key
            """,
            (guild_id, user_id, BAIT_SLOT, item.key),
        )
        await self._conn.commit()
        return BAIT_SLOT

    async def consume_item(self, guild_id: int, user_id: int, item_key: str) -> tuple[int, int]:
        """Mange un consommable. Renvoie `(énergie, max effectif)`."""
        item = self._item(item_key)
        cons = item.consumable
        if cons is None or not cons.consumed_on_use:
            raise PlayerError("cet item ne se consomme pas ainsi")
        effects = item.effects or {}
        restore_pct = effects.get("restore_energy_pct")
        bonus_pct = effects.get("max_energy_bonus_pct")
        if restore_pct is None and bonus_pct is None:
            raise PlayerError("cet item ne se mange pas")
        await self.get_or_create(guild_id, user_id)
        snap = await self.snapshot(guild_id, user_id)
        owned = next((s.quantity for s in snap.stacks if s.item_key == item.key), 0)
        if owned < 1:
            raise PlayerError("tu n'as pas cet item")
        new_qty = owned - 1
        if new_qty <= 0:
            await self._conn.execute(
                """
                DELETE FROM inventory_stacks
                WHERE guild_id = ? AND user_id = ? AND item_key = ?
                """,
                (guild_id, user_id, item.key),
            )
        else:
            await self._conn.execute(
                """
                UPDATE inventory_stacks SET quantity = ?
                WHERE guild_id = ? AND user_id = ? AND item_key = ?
                """,
                (new_qty, guild_id, user_id, item.key),
            )

        now = datetime.now(timezone.utc)
        energy = snap.energy
        eff_max = snap.energy_max
        if restore_pct is not None:
            heal = max(1, round(eff_max * float(restore_pct)))
            energy = min(eff_max, energy + heal)
        if bonus_pct is not None:
            minutes = int(effects.get("duration_minutes") or 30)
            until = now + timedelta(minutes=minutes)
            await self._conn.execute(
                """
                UPDATE players
                SET energy_bonus_pct = ?, energy_bonus_until = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (float(bonus_pct), until.isoformat(), guild_id, user_id),
            )
            eff_max = effective_energy_max(
                snap.energy_max_base, float(bonus_pct), until, now
            )
            energy = min(energy, eff_max)
        await self._conn.execute(
            """
            UPDATE players SET energy = ?, energy_updated_at = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (energy, now.isoformat(), guild_id, user_id),
        )
        await self._conn.commit()
        return energy, eff_max

    async def begin_cast(
        self,
        guild_id: int,
        user_id: int,
        *,
        rng: random.Random | None = None,
    ) -> PendingCast:
        """Paie énergie et appât, tire l'espèce, n'écrit pas le Dex."""
        rng = rng or random.Random()
        snap = await self.get_or_create(guild_id, user_id)
        if not snap.milieu_key:
            raise PlayerError("choisis un milieu avec /monde")
        tool_eq = snap.equipped.get("tool")
        tool_key = None
        if tool_eq is not None:
            tool_key = tool_eq.gear.item_key if tool_eq.gear is not None else tool_eq.item_key
        if not tool_key:
            raise PlayerError("équipe un outil avec /profil")
        tool = self._item(tool_key)
        method = tool.equipment.capture_method if tool.equipment else None
        if not method:
            raise PlayerError("cet outil n'a pas de méthode de capture")
        effects = collect_owned_effects(
            self.catalog, snap.gear, snap.stacks, snap.equipped
        )
        weather = weather_at(
            guild_id, snap.milieu_key, datetime.now(timezone.utc), self.catalog.game.world
        )
        ignore_weather = bool(effects.get("ignore_bad_weather_fatigue_penalty"))
        base, extra = cast_energy_parts(
            self.catalog, weather.key, ignore=ignore_weather
        )
        cost = base + extra
        if snap.energy < cost:
            raise PlayerError(
                energy_shortfall_message(
                    energy=snap.energy,
                    base=base,
                    extra=extra,
                    weather_label=weather_display(weather) if extra else "",
                )
            )

        bait_item = None
        bait_eq = snap.equipped.get(BAIT_SLOT)
        bait_key = bait_eq.item_key if bait_eq is not None else None
        if bait_key:
            bait_item = self._item(bait_key)
            owned = next((s.quantity for s in snap.stacks if s.item_key == bait_key), 0)
            if owned < 1:
                await self._conn.execute(
                    "DELETE FROM equipped WHERE guild_id = ? AND user_id = ? AND slot = ?",
                    (guild_id, user_id, BAIT_SLOT),
                )
                bait_item = None
                bait_key = None

        hook_item = None
        hook_eq = snap.equipped.get("hook")
        hook_key = None
        if hook_eq is not None:
            hook_key = hook_eq.gear.item_key if hook_eq.gear is not None else hook_eq.item_key
        if hook_key:
            hook_item = self._item(hook_key)

        raw_off = effects.get("offseason_species_chance_bonus")
        try:
            offseason = float(raw_off or 0)
        except (TypeError, ValueError):
            offseason = 0.0
        env_score = await self.environment_score(guild_id)
        ctx = context_from_world(
            self.catalog,
            guild_id,
            snap.milieu_key,
            method,
            bait=bait_item,
            hook=hook_item,
            ignore_night_penalty=bool(effects.get("ignore_night_fishing_success_penalty")),
            offseason_bonus=offseason,
            env_quality_mult=env_quality_mult(self.catalog, env_score),
        )
        pool = build_pool(self.catalog, ctx)
        try:
            species = roll(pool, rng)
        except FishingError as exc:
            raise PlayerError(str(exc)) from exc

        new_energy = snap.energy - cost
        await self._conn.execute(
            """
            UPDATE players SET energy = ?, energy_updated_at = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (new_energy, _now(), guild_id, user_id),
        )

        bait_consumed: str | None = None
        if bait_item is not None and bait_key is not None:
            cons = bait_item.consumable
            if cons is not None and cons.consumed_on_attempt:
                owned = next((s.quantity for s in snap.stacks if s.item_key == bait_key), 0)
                new_qty = owned - 1
                if new_qty <= 0:
                    await self._conn.execute(
                        """
                        DELETE FROM inventory_stacks
                        WHERE guild_id = ? AND user_id = ? AND item_key = ?
                        """,
                        (guild_id, user_id, bait_key),
                    )
                    await self._conn.execute(
                        "DELETE FROM equipped WHERE guild_id = ? AND user_id = ? AND slot = ?",
                        (guild_id, user_id, BAIT_SLOT),
                    )
                else:
                    await self._conn.execute(
                        """
                        UPDATE inventory_stacks SET quantity = ?
                        WHERE guild_id = ? AND user_id = ? AND item_key = ?
                        """,
                        (new_qty, guild_id, user_id, bait_key),
                    )
                bait_consumed = bait_key

        await self._conn.commit()
        timings = bite_timings(
            self.catalog.game.fishing.minigame, method, hook=hook_item, rng=rng
        )
        fresh = await self.snapshot(guild_id, user_id)
        return PendingCast(
            guild_id=guild_id,
            user_id=user_id,
            species_key=species.key,
            method=method,
            energy=fresh.energy,
            energy_max=fresh.energy_max,
            bait_consumed=bait_consumed,
            wait_s=timings.wait_s,
            window_s=timings.window_s,
            trap_early=timings.trap_early,
            action_label=timings.action_label,
            milieu_key=snap.milieu_key,
            weather_key=weather.key,
            tool_key=tool_key,
            hook_key=hook_key,
            bait_key=bait_key,
        )

    async def preview_cast(
        self,
        guild_id: int,
        user_id: int,
        species_key: str,
        *,
        bait_consumed: str | None = None,
        rng: random.Random | None = None,
        specimen: Specimen | None = None,
        energy: int | None = None,
        energy_max: int | None = None,
    ) -> CastResult:
        """Calcule spécimen et records sans écrire le Dex."""
        rng = rng or random.Random()
        try:
            species = self.catalog.get_species(species_key)
        except CatalogError as exc:
            raise PlayerError(f"espèce inconnue : {species_key!r}") from exc
        if specimen is None:
            beat = None
            if bait_consumed:
                try:
                    bait = self._item(bait_consumed)
                except PlayerError:
                    bait = None
                if bait is not None and (bait.effects or {}).get("guarantee_personal_record"):
                    async with self._conn.execute(
                        """
                        SELECT best_length_cm, best_weight_kg FROM fishdex
                        WHERE guild_id = ? AND user_id = ? AND species_key = ?
                        """,
                        (guild_id, user_id, species.key),
                    ) as cur:
                        prev = await cur.fetchone()
                    if prev is not None and prev["best_length_cm"] is not None:
                        beat = Specimen(
                            float(prev["best_length_cm"]),
                            float(prev["best_weight_kg"] or 0),
                        )
            specimen = generate_specimen(
                species, self.catalog.game.fishing.specimen, rng, beat=beat
            )
        catch_count, is_new, personal_record, guild_rank = await self._evaluate_catch(
            guild_id, user_id, species.key, specimen
        )
        kept, carry_used, carry_max = await self._carry_preview(
            guild_id, user_id, species.key
        )
        if energy is None or energy_max is None:
            row = await self._fetch_player_row(guild_id, user_id)
            if row is not None:
                energy = int(row["energy"]) if energy is None else energy
                energy_max = int(row["energy_max"]) if energy_max is None else energy_max
        return CastResult(
            species_key=species.key,
            catch_count=catch_count,
            is_new=is_new,
            energy=0 if energy is None else energy,
            energy_max=0 if energy_max is None else energy_max,
            bait_consumed=bait_consumed,
            length_cm=specimen.length_cm,
            weight_kg=specimen.weight_kg,
            personal_record=personal_record,
            guild_rank=guild_rank,
            kept=kept,
            carry_used=carry_used,
            carry_max=carry_max,
        )

    async def finish_cast(
        self,
        guild_id: int,
        user_id: int,
        species_key: str,
        *,
        bait_consumed: str | None = None,
        rng: random.Random | None = None,
        specimen: Specimen | None = None,
        energy: int | None = None,
        energy_max: int | None = None,
        preview: CastResult | None = None,
    ) -> CastResult:
        """Enregistre la capture : spécimen, Dex, records."""
        rng = rng or random.Random()
        if preview is not None:
            if specimen is None and preview.length_cm is not None and preview.weight_kg is not None:
                specimen = Specimen(preview.length_cm, preview.weight_kg)
            result = preview
            if energy is not None:
                result = replace(result, energy=energy)
            if energy_max is not None:
                result = replace(result, energy_max=energy_max)
            if bait_consumed is not None:
                result = replace(result, bait_consumed=bait_consumed)
        else:
            if energy is None or energy_max is None:
                if await self._fetch_player_row(guild_id, user_id) is None:
                    await self.get_or_create(guild_id, user_id)
            result = await self.preview_cast(
                guild_id,
                user_id,
                species_key,
                bait_consumed=bait_consumed,
                rng=rng,
                specimen=specimen,
                energy=energy,
                energy_max=energy_max,
            )
            if specimen is None and result.length_cm is not None and result.weight_kg is not None:
                specimen = Specimen(result.length_cm, result.weight_kg)
        if specimen is None:
            raise PlayerError("spécimen manquant")
        catch_count, kept, carry_used, carry_max = await self._persist_catch(
            guild_id, user_id, result.species_key, specimen
        )
        snap = result.snap
        out_energy = result.energy
        out_max = result.energy_max
        if energy is None or energy_max is None:
            snap = await self.snapshot(guild_id, user_id)
            out_energy = snap.energy
            out_max = snap.energy_max
        waste = roll_waste(self.catalog, rng)
        waste_key = None
        if waste is not None:
            await self.add_item(guild_id, user_id, waste.key, 1)
            waste_key = waste.key
        loot = roll_loot(self.catalog, rng)
        loot_key = None
        if loot is not None:
            await self.add_item(guild_id, user_id, loot.key, 1)
            loot_key = loot.key
        hook_broke = await self._wear_hooked_attempt(guild_id, user_id)
        milieu_key = snap.milieu_key if snap is not None else None
        if milieu_key:
            await self._record_milieu_catch(guild_id, milieu_key)
        return replace(
            result,
            catch_count=catch_count,
            is_new=catch_count == 1,
            energy=out_energy,
            energy_max=out_max,
            snap=snap,
            kept=kept,
            carry_used=carry_used,
            carry_max=carry_max,
            waste_key=waste_key,
            loot_key=loot_key,
            hook_broke=hook_broke,
        )

    async def _evaluate_catch(
        self,
        guild_id: int,
        user_id: int,
        species_key: str,
        specimen: Specimen,
    ) -> tuple[int, bool, bool, int | None]:
        try:
            species = self.catalog.get_species(species_key)
        except CatalogError as exc:
            raise PlayerError(f"espèce inconnue : {species_key!r}") from exc
        recordable = bool(species.collection.recordable)
        old_best_len = None
        old_best_w = None
        prev_count = 0
        async with self._conn.execute(
            """
            SELECT catch_count, best_length_cm, best_weight_kg FROM fishdex
            WHERE guild_id = ? AND user_id = ? AND species_key = ?
            """,
            (guild_id, user_id, species_key),
        ) as cur:
            prev = await cur.fetchone()
            if prev is not None:
                prev_count = int(prev["catch_count"])
                old_best_len = prev["best_length_cm"]
                old_best_w = prev["best_weight_kg"]
        is_new = prev is None
        catch_count = prev_count + 1
        personal_record = False
        if recordable:
            personal_record = _specimen_better(
                specimen.length_cm, specimen.weight_kg, old_best_len, old_best_w
            )
        guild_rank: int | None = None
        if recordable:
            rows: list[tuple[int, float, float]] = []
            own_len = None
            own_w = None
            async with self._conn.execute(
                """
                SELECT user_id, length_cm, weight_kg FROM guild_records
                WHERE guild_id = ? AND species_key = ?
                """,
                (guild_id, species_key),
            ) as cur:
                async for r in cur:
                    uid = int(r["user_id"])
                    length = float(r["length_cm"])
                    weight = float(r["weight_kg"])
                    rows.append((uid, length, weight))
                    if uid == user_id:
                        own_len = length
                        own_w = weight
            if _specimen_better(specimen.length_cm, specimen.weight_kg, own_len, own_w):
                rows = [row for row in rows if row[0] != user_id]
                rows.append((user_id, specimen.length_cm, specimen.weight_kg))
                rows.sort(key=lambda row: (-row[1], -row[2], row[0]))
                pos = next((i for i, row in enumerate(rows, start=1) if row[0] == user_id), 0)
                if 1 <= pos <= 3:
                    guild_rank = pos
        return catch_count, is_new, personal_record, guild_rank

    async def _persist_catch(
        self,
        guild_id: int,
        user_id: int,
        species_key: str,
        specimen: Specimen,
    ) -> tuple[int, bool, int, int]:
        try:
            species = self.catalog.get_species(species_key)
        except CatalogError as exc:
            raise PlayerError(f"espèce inconnue : {species_key!r}") from exc
        recordable = bool(species.collection.recordable)
        now = _now()
        cur = await self._conn.execute(
            """
            INSERT INTO fishdex (
                guild_id, user_id, species_key, catch_count, first_caught_at,
                best_length_cm, best_weight_kg, last_length_cm, last_weight_kg
            )
            VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, species_key)
            DO UPDATE SET
                catch_count = catch_count + 1,
                last_length_cm = excluded.last_length_cm,
                last_weight_kg = excluded.last_weight_kg,
                best_length_cm = MAX(
                    COALESCE(fishdex.best_length_cm, excluded.last_length_cm),
                    excluded.last_length_cm
                ),
                best_weight_kg = MAX(
                    COALESCE(fishdex.best_weight_kg, excluded.last_weight_kg),
                    excluded.last_weight_kg
                )
            RETURNING catch_count
            """,
            (
                guild_id,
                user_id,
                species_key,
                now,
                specimen.length_cm,
                specimen.weight_kg,
                specimen.length_cm,
                specimen.weight_kg,
            ),
        )
        count_row = await cur.fetchone()
        catch_count = int(count_row["catch_count"]) if count_row is not None else 1
        if recordable:
            own_len = None
            own_w = None
            async with self._conn.execute(
                """
                SELECT length_cm, weight_kg FROM guild_records
                WHERE guild_id = ? AND species_key = ? AND user_id = ?
                """,
                (guild_id, species_key, user_id),
            ) as cur:
                own = await cur.fetchone()
                if own is not None:
                    own_len = own["length_cm"]
                    own_w = own["weight_kg"]
            if _specimen_better(specimen.length_cm, specimen.weight_kg, own_len, own_w):
                await self._conn.execute(
                    """
                    INSERT INTO guild_records (
                        guild_id, species_key, user_id, length_cm, weight_kg, caught_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(guild_id, species_key, user_id)
                    DO UPDATE SET
                        length_cm = excluded.length_cm,
                        weight_kg = excluded.weight_kg,
                        caught_at = excluded.caught_at
                    """,
                    (
                        guild_id,
                        species_key,
                        user_id,
                        specimen.length_cm,
                        specimen.weight_kg,
                        now,
                    ),
                )
        kept, carry_used, carry_max = await self._maybe_keep_specimen(
            guild_id, user_id, species_key, specimen, now
        )
        await self._conn.commit()
        return catch_count, kept, carry_used, carry_max

    async def cast(
        self,
        guild_id: int,
        user_id: int,
        *,
        rng: random.Random | None = None,
    ) -> CastResult:
        """Lancer + capture auto (tests). Le jeu Discord passe par begin/finish."""
        rng = rng or random.Random()
        pending = await self.begin_cast(guild_id, user_id, rng=rng)
        return await self.finish_cast(
            guild_id,
            user_id,
            pending.species_key,
            bait_consumed=pending.bait_consumed,
            rng=rng,
        )

    async def list_guild_records(
        self, guild_id: int, *, limit: int = 15
    ) -> list[tuple[str, int, float, float]]:
        """Meilleure prise guild par espèce, triée par taille."""
        best: dict[str, tuple[int, float, float]] = {}
        async with self._conn.execute(
            """
            SELECT species_key, user_id, length_cm, weight_kg
            FROM guild_records WHERE guild_id = ?
            """,
            (guild_id,),
        ) as cur:
            async for row in cur:
                key = str(row["species_key"])
                length = float(row["length_cm"])
                weight = float(row["weight_kg"])
                prev = best.get(key)
                if prev is None or length > prev[1] or (length == prev[1] and weight > prev[2]):
                    best[key] = (int(row["user_id"]), length, weight)
        ranked = sorted(best.items(), key=lambda kv: (-kv[1][1], -kv[1][2]))
        return [(key, uid, length, weight) for key, (uid, length, weight) in ranked[:limit]]

    async def list_dex(self, guild_id: int, user_id: int) -> dict[str, DexRow]:
        await self.get_or_create(guild_id, user_id)
        out: dict[str, DexRow] = {}
        async with self._conn.execute(
            """
            SELECT species_key, catch_count, first_caught_at,
                   best_length_cm, best_weight_kg, last_length_cm, last_weight_kg
            FROM fishdex
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ) as cur:
            async for r in cur:
                out[r["species_key"]] = DexRow(
                    species_key=r["species_key"],
                    catch_count=int(r["catch_count"]),
                    first_caught_at=r["first_caught_at"],
                    best_length_cm=None if r["best_length_cm"] is None else float(r["best_length_cm"]),
                    best_weight_kg=None if r["best_weight_kg"] is None else float(r["best_weight_kg"]),
                    last_length_cm=None if r["last_length_cm"] is None else float(r["last_length_cm"]),
                    last_weight_kg=None if r["last_weight_kg"] is None else float(r["last_weight_kg"]),
                )
        return out

    async def list_caught(self, guild_id: int, user_id: int) -> list[CaughtSpecimen]:
        await self.get_or_create(guild_id, user_id)
        out: list[CaughtSpecimen] = []
        async with self._conn.execute(
            """
            SELECT id, species_key, length_cm, weight_kg, caught_at
            FROM caught_specimens
            WHERE guild_id = ? AND user_id = ?
            ORDER BY id DESC
            """,
            (guild_id, user_id),
        ) as cur:
            async for r in cur:
                out.append(
                    CaughtSpecimen(
                        id=int(r["id"]),
                        species_key=r["species_key"],
                        length_cm=float(r["length_cm"]),
                        weight_kg=float(r["weight_kg"]),
                        caught_at=r["caught_at"],
                    )
                )
        return out

    async def release_caught(
        self, guild_id: int, user_id: int, specimen_id: int
    ) -> CaughtSpecimen:
        async with self._conn.execute(
            """
            SELECT id, species_key, length_cm, weight_kg, caught_at
            FROM caught_specimens
            WHERE id = ? AND guild_id = ? AND user_id = ?
            """,
            (specimen_id, guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise PlayerError("prise introuvable")
        await self._conn.execute(
            "DELETE FROM caught_specimens WHERE id = ? AND guild_id = ? AND user_id = ?",
            (specimen_id, guild_id, user_id),
        )
        await self._conn.commit()
        return CaughtSpecimen(
            id=int(row["id"]),
            species_key=row["species_key"],
            length_cm=float(row["length_cm"]),
            weight_kg=float(row["weight_kg"]),
            caught_at=row["caught_at"],
        )

    async def _load_gear_and_stacks(
        self, guild_id: int, user_id: int
    ) -> tuple[list[GearInstance], list[Stack]]:
        stacks: list[Stack] = []
        async with self._conn.execute(
            """
            SELECT item_key, quantity FROM inventory_stacks
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ) as cur:
            async for r in cur:
                stacks.append(Stack(item_key=r["item_key"], quantity=int(r["quantity"])))
        gear: list[GearInstance] = []
        async with self._conn.execute(
            """
            SELECT id, item_key, durability FROM gear_instances
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ) as cur:
            async for r in cur:
                gear.append(
                    GearInstance(
                        id=int(r["id"]),
                        item_key=r["item_key"],
                        durability=r["durability"] if r["durability"] is None else int(r["durability"]),
                    )
                )
        return gear, stacks

    async def _load_equipped(
        self,
        guild_id: int,
        user_id: int,
        gear_by_id: dict[int, GearInstance],
    ) -> dict[str, EquippedSlot]:
        equipped: dict[str, EquippedSlot] = {}
        async with self._conn.execute(
            """
            SELECT slot, gear_id, item_key FROM equipped
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ) as cur:
            async for r in cur:
                slot = r["slot"]
                gear_id = int(r["gear_id"]) if r["gear_id"] is not None else None
                equipped[slot] = EquippedSlot(
                    slot=slot,
                    gear_id=gear_id,
                    item_key=r["item_key"],
                    gear=gear_by_id.get(gear_id) if gear_id is not None else None,
                )
        return equipped

    async def _count_caught_by_compartment(
        self, guild_id: int, user_id: int
    ) -> tuple[int, int]:
        fish_n = 0
        creature_n = 0
        async with self._conn.execute(
            "SELECT species_key FROM caught_specimens WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cur:
            async for r in cur:
                if carry_compartment(self.catalog, r["species_key"]) == "fish":
                    fish_n += 1
                else:
                    creature_n += 1
        return fish_n, creature_n

    async def _compartment_state(
        self, guild_id: int, user_id: int, species_key: str
    ) -> tuple[int, int]:
        gear, stacks = await self._load_gear_and_stacks(guild_id, user_id)
        equipped = await self._load_equipped(guild_id, user_id, {g.id: g for g in gear})
        fish_max, creature_max = carry_limits(self.catalog, gear, stacks, equipped)
        fish_n, creature_n = await self._count_caught_by_compartment(guild_id, user_id)
        if carry_compartment(self.catalog, species_key) == "fish":
            return fish_n, fish_max
        return creature_n, creature_max

    async def _carry_preview(
        self, guild_id: int, user_id: int, species_key: str
    ) -> tuple[bool, int, int]:
        used, cap = await self._compartment_state(guild_id, user_id, species_key)
        if used < cap:
            return True, used + 1, cap
        return False, used, cap

    async def _maybe_keep_specimen(
        self,
        guild_id: int,
        user_id: int,
        species_key: str,
        specimen: Specimen,
        caught_at: str,
    ) -> tuple[bool, int, int]:
        used, cap = await self._compartment_state(guild_id, user_id, species_key)
        if used >= cap:
            return False, used, cap
        await self._conn.execute(
            """
            INSERT INTO caught_specimens (
                guild_id, user_id, species_key, length_cm, weight_kg, caught_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                user_id,
                species_key,
                specimen.length_cm,
                specimen.weight_kg,
                caught_at,
            ),
        )
        return True, used + 1, cap

    async def reset_player(self, guild_id: int, user_id: int) -> None:
        await self._conn.execute(
            "DELETE FROM guild_records WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self._conn.execute(
            "DELETE FROM caught_specimens WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self._conn.execute(
            "DELETE FROM fishdex WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self._conn.execute(
            "DELETE FROM equipped WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self._conn.execute(
            "DELETE FROM gear_instances WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self._conn.execute(
            "DELETE FROM inventory_stacks WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self._conn.execute(
            "DELETE FROM village_talk WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self._conn.execute(
            "DELETE FROM players WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self._conn.commit()

    async def environment_score(self, guild_id: int) -> int:
        async with self._conn.execute(
            "SELECT environment_score FROM guild_state WHERE guild_id = ?",
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return int(self.catalog.game.village.environment_score_start)
        return clamp_environment_score(self.catalog, int(row["environment_score"]))

    async def add_environment_score(
        self, guild_id: int, delta: int, *, commit: bool = True
    ) -> int:
        current = await self.environment_score(guild_id)
        new = clamp_environment_score(self.catalog, current + int(delta))
        if new == current and delta == 0:
            return current
        await self._conn.execute(
            """
            INSERT INTO guild_state (guild_id, environment_score)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                environment_score = excluded.environment_score
            """,
            (guild_id, new),
        )
        if commit:
            await self._conn.commit()
        return new

    async def _record_milieu_catch(self, guild_id: int, milieu_key: str) -> None:
        village = self.catalog.game.village
        bucket = village_bucket(self.catalog)
        await self._conn.execute(
            """
            INSERT INTO guild_milieu_catches (
                guild_id, milieu_key, bucket, catch_count
            )
            VALUES (?, ?, ?, 1)
            ON CONFLICT(guild_id, milieu_key, bucket)
            DO UPDATE SET catch_count = catch_count + 1
            """,
            (guild_id, milieu_key, bucket),
        )
        async with self._conn.execute(
            """
            SELECT catch_count FROM guild_milieu_catches
            WHERE guild_id = ? AND milieu_key = ? AND bucket = ?
            """,
            (guild_id, milieu_key, bucket),
        ) as cur:
            row = await cur.fetchone()
        count = int(row["catch_count"]) if row is not None else 1
        if count > int(village.overfish_per_bucket) and village.overfish_score_loss:
            await self.add_environment_score(
                guild_id, -int(village.overfish_score_loss), commit=False
            )
        await self._conn.commit()

    async def list_village_announcements(self, guild_id: int) -> list[VillageAnnouncement]:
        now = _now()
        out: list[VillageAnnouncement] = []
        async with self._conn.execute(
            """
            SELECT id, guild_id, npc_key, text, modifier, starts_at, ends_at
            FROM village_announcements
            WHERE guild_id = ? AND starts_at <= ? AND ends_at > ?
            ORDER BY id
            """,
            (guild_id, now, now),
        ) as cur:
            async for row in cur:
                raw = row["modifier"]
                modifier: dict[str, Any] = {}
                if raw:
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed = {}
                    if isinstance(parsed, dict):
                        modifier = parsed
                out.append(
                    VillageAnnouncement(
                        id=int(row["id"]),
                        guild_id=int(row["guild_id"]),
                        npc_key=row["npc_key"],
                        text=row["text"] or "",
                        modifier=modifier,
                        starts_at=row["starts_at"],
                        ends_at=row["ends_at"],
                    )
                )
        return out

    async def post_village_announcement(
        self,
        guild_id: int,
        npc_key: str,
        text: str,
        *,
        hours: int = 6,
        modifier: dict[str, Any] | None = None,
    ) -> VillageAnnouncement:
        hours = max(1, int(hours))
        if not modifier or not infer_modifier_kind(modifier):
            raise PlayerError("l'annonce doit avoir un effet")
        starts = datetime.now(timezone.utc)
        ends = starts + timedelta(hours=hours)
        payload = json.dumps(dict(modifier), ensure_ascii=False)
        cur = await self._conn.execute(
            """
            INSERT INTO village_announcements (
                guild_id, npc_key, text, modifier, starts_at, ends_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild_id, npc_key, text, payload, starts.isoformat(), ends.isoformat()),
        )
        await self._conn.commit()
        ann_id = int(cur.lastrowid or 0)
        return VillageAnnouncement(
            id=ann_id,
            guild_id=guild_id,
            npc_key=npc_key,
            text=text,
            modifier=dict(modifier or {}),
            starts_at=starts.isoformat(),
            ends_at=ends.isoformat(),
        )

    async def expire_village_announcements(self) -> int:
        cur = await self._conn.execute(
            "DELETE FROM village_announcements WHERE ends_at <= ?",
            (_now(),),
        )
        await self._conn.commit()
        return int(cur.rowcount or 0)

    async def sell_specimen(self, guild_id: int, user_id: int, specimen_id: int) -> tuple[int, str, int]:
        """Vend une prise. Renvoie `(prix, species_key, argent)`."""
        await self.get_or_create(guild_id, user_id)
        async with self._conn.execute(
            """
            SELECT id, species_key, length_cm, weight_kg, caught_at
            FROM caught_specimens
            WHERE id = ? AND guild_id = ? AND user_id = ?
            """,
            (specimen_id, guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise PlayerError("prise introuvable")
        species_key = str(row["species_key"])
        try:
            species = self.catalog.get_species(species_key)
        except CatalogError as exc:
            raise PlayerError(f"espèce inconnue : {species_key!r}") from exc
        if not species.economy.sellable:
            raise PlayerError("cette prise ne se vend pas")
        price = specimen_price(
            self.catalog,
            species,
            float(row["length_cm"]),
            float(row["weight_kg"]),
            modifiers=await self.trade_modifiers(guild_id, user_id),
        )
        deleted = await self._conn.execute(
            "DELETE FROM caught_specimens WHERE id = ? AND guild_id = ? AND user_id = ?",
            (specimen_id, guild_id, user_id),
        )
        if int(deleted.rowcount or 0) != 1:
            raise PlayerError("prise introuvable")
        snap = await self.snapshot(guild_id, user_id)
        new_money = snap.money + price
        await self._conn.execute(
            "UPDATE players SET money = ? WHERE guild_id = ? AND user_id = ?",
            (new_money, guild_id, user_id),
        )
        await self._conn.commit()
        return price, species_key, new_money

    async def sell_item(
        self,
        guild_id: int,
        user_id: int,
        item_key: str,
        *,
        quantity: int = 1,
        gear_id: int | None = None,
    ) -> tuple[int, int, int]:
        """Vend un item. Renvoie `(prix, argent, score env gagné)`."""
        if quantity < 1:
            raise PlayerError("la quantité doit être ≥ 1")
        item = self._item(item_key)
        sell_price = item.economy.sell_price
        if sell_price is None:
            raise PlayerError("cet item ne se vend pas")
        await self.get_or_create(guild_id, user_id)
        snap = await self.snapshot(guild_id, user_id)
        if _is_stackable(item):
            await self._consume_stack(guild_id, user_id, item.key, quantity)
            total = int(sell_price) * quantity
        else:
            if gear_id is None:
                raise PlayerError("instance introuvable")
            await self._delete_gear(guild_id, user_id, gear_id, expected_key=item.key)
            total = int(sell_price)
        mods = await self.trade_modifiers(guild_id, user_id)
        if item.category == "waste":
            total = apply_named_mult(total, mods, "waste_mult")
        else:
            total = apply_named_mult(total, mods, "sell_mult")
        env_gain = 0
        raw_env = (item.effects or {}).get("environment_cleanup_score")
        if raw_env is not None:
            try:
                env_gain = max(0, int(raw_env)) * (quantity if _is_stackable(item) else 1)
            except (TypeError, ValueError):
                env_gain = 0
        new_money = snap.money + total
        await self._conn.execute(
            "UPDATE players SET money = ? WHERE guild_id = ? AND user_id = ?",
            (new_money, guild_id, user_id),
        )
        if env_gain:
            await self.add_environment_score(guild_id, env_gain, commit=False)
        await self._conn.commit()
        return total, new_money, env_gain

    async def buy_item(
        self,
        guild_id: int,
        user_id: int,
        item_key: str,
        quantity: int = 1,
        *,
        seller_key: str | None = None,
    ) -> tuple[int, int]:
        """Achète un item du rayon d'un vendeur. Renvoie `(dépense, argent)`."""
        if quantity < 1:
            raise PlayerError("la quantité doit être ≥ 1")
        item = self._item(item_key)
        buy_price = item.economy.buy_price
        if not item.enabled or buy_price is None:
            raise PlayerError("cet item n'est pas en vente")
        seller = None
        if seller_key:
            try:
                seller = self.catalog.get_npc(seller_key)
            except CatalogError as exc:
                raise PlayerError("ce marchand n'est pas là") from exc
            if seller.shop_mode != "sell":
                raise PlayerError("ce villageois ne vend rien")
        stock = {it.key for it in shop_stock(self.catalog, seller)}
        if item.key not in stock:
            raise PlayerError("cet item n'est pas en rayon")
        await self.get_or_create(guild_id, user_id)
        snap = await self.snapshot(guild_id, user_id)
        unit = apply_named_mult(
            int(buy_price),
            await self.trade_modifiers(guild_id, user_id, seller_key),
            "buy_mult",
        )
        cost = unit * quantity
        if snap.money < cost:
            raise PlayerError("pas assez d'argent")
        added = await self.add_item(
            guild_id, user_id, item.key, quantity, auto_equip=True, commit=False
        )
        if added < 1:
            raise PlayerError("pas de place dans le sac")
        paid = unit * added
        if snap.money < paid:
            raise PlayerError("pas assez d'argent")
        new_money = snap.money - paid
        await self._conn.execute(
            "UPDATE players SET money = ? WHERE guild_id = ? AND user_id = ?",
            (new_money, guild_id, user_id),
        )
        await self._conn.commit()
        return paid, new_money

    async def travel_to(
        self, guild_id: int, user_id: int, milieu_key: str
    ) -> tuple[bool, str, int]:
        """Passage instantané. Prix plein, ou au prorata si déjà en route. Renvoie `(changé, key, argent)`."""
        try:
            milieu = self.catalog.get_milieu(milieu_key)
        except CatalogError as exc:
            raise PlayerError(f"milieu inconnu : {milieu_key!r}") from exc
        await self.get_or_create(guild_id, user_id)
        snap = await self.snapshot(guild_id, user_id)
        if snap.milieu_key == milieu.key:
            if snap.travel_dest:
                await self._conn.execute(
                    """
                    UPDATE players
                    SET travel_dest = NULL, travel_arrives_at = NULL
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (guild_id, user_id),
                )
                await self._conn.commit()
            return False, milieu.key, snap.money
        remaining = None
        if snap.travel_dest == milieu.key:
            remaining = travel_remaining_s(snap.travel_arrives_at)
        cost = passeur_price(self.catalog, remaining_s=remaining, snap=snap)
        cost = apply_named_mult(
            cost,
            await self.trade_modifiers(guild_id, user_id),
            "travel_mult",
        )
        if cost > 0 and snap.money < cost:
            raise PlayerError("pas assez d'argent pour le passage")
        new_money = snap.money - cost
        await self._conn.execute(
            """
            UPDATE players
            SET milieu_key = ?, money = ?, travel_dest = NULL, travel_arrives_at = NULL
            WHERE guild_id = ? AND user_id = ?
            """,
            (milieu.key, new_money, guild_id, user_id),
        )
        await self._conn.commit()
        return True, milieu.key, new_money

    async def list_village_talk(
        self,
        guild_id: int,
        user_id: int,
        npc_key: str,
        *,
        limit: int = 6,
        bucket: int | None = None,
    ) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        sql = """
            SELECT question, response FROM village_talk
            WHERE guild_id = ? AND user_id = ? AND npc_key = ?
        """
        params: list[Any] = [guild_id, user_id, npc_key]
        if bucket is not None:
            sql += " AND bucket = ?"
            params.append(bucket)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        async with self._conn.execute(sql, params) as cur:
            async for row in cur:
                out.append((row["question"], row["response"]))
        out.reverse()
        return out

    async def last_village_talk(
        self, guild_id: int, user_id: int, npc_key: str, *, bucket: int
    ) -> VillageTalkState | None:
        async with self._conn.execute(
            """
            SELECT npc_key, question, response, intent, item_key, milieu_key,
                   display, board_keys, quantity, bucket
            FROM village_talk
            WHERE guild_id = ? AND user_id = ? AND npc_key = ? AND bucket = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (guild_id, user_id, npc_key, bucket),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        keys: list[str] = []
        raw_keys = row["board_keys"]
        if raw_keys:
            try:
                parsed = json.loads(raw_keys)
            except json.JSONDecodeError:
                parsed = []
            if isinstance(parsed, list):
                keys = [str(k) for k in parsed if str(k).strip()]
        return VillageTalkState(
            npc_key=str(row["npc_key"]),
            question=str(row["question"] or ""),
            response=str(row["response"] or ""),
            intent=str(row["intent"] or "none"),
            item_key=row["item_key"],
            milieu_key=row["milieu_key"],
            display=str(row["display"] or "none"),
            board_keys=keys,
            quantity=max(1, int(row["quantity"] or 1)),
            bucket=int(row["bucket"] or 0),
        )

    async def record_village_talk(
        self,
        guild_id: int,
        user_id: int,
        npc_key: str,
        question: str,
        response: str,
        *,
        bucket: int,
        intent: str = "none",
        item_key: str | None = None,
        milieu_key: str | None = None,
        display: str = "none",
        board_keys: list[str] | None = None,
        quantity: int = 1,
    ) -> None:
        await self._conn.execute(
            """
            INSERT INTO village_talk (
                guild_id, user_id, npc_key, question, response, created_at,
                intent, item_key, milieu_key, display, board_keys, quantity, bucket
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                user_id,
                npc_key,
                question,
                response,
                _now(),
                intent,
                item_key,
                milieu_key,
                display,
                json.dumps(list(board_keys or [])),
                max(1, int(quantity)),
                bucket,
            ),
        )
        await self._conn.commit()

    async def clear_village_talk_intent(
        self, guild_id: int, user_id: int, npc_key: str
    ) -> None:
        async with self._conn.execute(
            """
            SELECT id FROM village_talk
            WHERE guild_id = ? AND user_id = ? AND npc_key = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (guild_id, user_id, npc_key),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return
        await self._conn.execute(
            """
            UPDATE village_talk
            SET intent = 'none', item_key = NULL, milieu_key = NULL, quantity = 1
            WHERE id = ?
            """,
            (int(row["id"]),),
        )
        await self._conn.commit()

    async def village_focus(
        self, guild_id: int, user_id: int
    ) -> tuple[str | None, int | None]:
        async with self._conn.execute(
            """
            SELECT village_npc_key, village_bucket FROM players
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None, None
        key = row["village_npc_key"]
        raw_bucket = row["village_bucket"]
        return (
            str(key) if key else None,
            int(raw_bucket) if raw_bucket is not None else None,
        )

    async def set_village_focus(
        self,
        guild_id: int,
        user_id: int,
        npc_key: str | None,
        bucket: int,
    ) -> None:
        await self.get_or_create(guild_id, user_id)
        await self._conn.execute(
            """
            UPDATE players
            SET village_npc_key = ?, village_bucket = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (npc_key, bucket, guild_id, user_id),
        )
        await self._conn.commit()

    async def get_village_bargain(
        self,
        guild_id: int,
        user_id: int,
        npc_key: str,
        *,
        bucket: int | None = None,
    ) -> dict[str, Any] | None:
        if bucket is None:
            bucket = village_bucket(self.catalog)
        async with self._conn.execute(
            """
            SELECT modifier FROM village_bargains
            WHERE guild_id = ? AND user_id = ? AND npc_key = ? AND bucket = ?
            """,
            (guild_id, user_id, npc_key, bucket),
        ) as cur:
            row = await cur.fetchone()
        if row is None or not row["modifier"]:
            return None
        try:
            parsed = json.loads(row["modifier"])
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    async def set_village_bargain(
        self,
        guild_id: int,
        user_id: int,
        npc: Npc,
        *,
        bucket: int | None = None,
    ) -> bool:
        if not npc_can_bargain(npc):
            return False
        if bucket is None:
            bucket = village_bucket(self.catalog)
        if await self.get_village_bargain(guild_id, user_id, npc.key, bucket=bucket):
            return False
        await self.get_or_create(guild_id, user_id)
        await self._conn.execute(
            """
            INSERT OR IGNORE INTO village_bargains (
                guild_id, user_id, npc_key, bucket, modifier, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                user_id,
                npc.key,
                bucket,
                json.dumps(bargain_modifier(self.catalog, npc)),
                _now(),
            ),
        )
        await self._conn.commit()
        return bool(
            await self.get_village_bargain(guild_id, user_id, npc.key, bucket=bucket)
        )

    async def trade_modifiers(
        self,
        guild_id: int,
        user_id: int,
        npc_key: str | None = None,
        *,
        bucket: int | None = None,
    ) -> list[dict[str, Any]]:
        anns = await self.list_village_announcements(guild_id)
        key = npc_key
        if not key:
            key, _focus_bucket = await self.village_focus(guild_id, user_id)
        bargain = None
        if key:
            bargain = await self.get_village_bargain(
                guild_id, user_id, key, bucket=bucket
            )
        return price_modifiers(anns, bargain)

    async def repair_gear(self, guild_id: int, user_id: int, gear_id: int) -> tuple[int, int]:
        """Répare une instance. Renvoie `(coût, argent)`."""
        await self.get_or_create(guild_id, user_id)
        async with self._conn.execute(
            """
            SELECT id, item_key, durability FROM gear_instances
            WHERE id = ? AND guild_id = ? AND user_id = ?
            """,
            (gear_id, guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise PlayerError("équipement introuvable")
        item = self._item(str(row["item_key"]))
        dur = item.durability
        if dur is None or not dur.repairable:
            raise PlayerError("cet équipement ne se répare pas")
        cost = dur.repair_cost
        if cost is None:
            raise PlayerError("cet équipement ne se répare pas")
        maximum = _max_durability(item)
        current = None if row["durability"] is None else int(row["durability"])
        if maximum is None or current is None or current >= maximum:
            raise PlayerError("déjà en bon état")
        cost = apply_named_mult(
            int(cost),
            await self.trade_modifiers(guild_id, user_id),
            "repair_mult",
        )
        snap = await self.snapshot(guild_id, user_id)
        if snap.money < cost:
            raise PlayerError("pas assez d'argent")
        new_money = snap.money - cost
        await self._conn.execute(
            "UPDATE gear_instances SET durability = ? WHERE id = ? AND guild_id = ? AND user_id = ?",
            (maximum, gear_id, guild_id, user_id),
        )
        await self._conn.execute(
            "UPDATE players SET money = ? WHERE guild_id = ? AND user_id = ?",
            (new_money, guild_id, user_id),
        )
        await self._conn.commit()
        return int(cost), new_money

    async def exchange_fossil(
        self,
        guild_id: int,
        user_id: int,
        *,
        rng: random.Random | None = None,
    ) -> str:
        """Échange 1 fossile dans la pierre contre une réplique. Renvoie la clé."""
        await self.get_or_create(guild_id, user_id)
        snap = await self.snapshot(guild_id, user_id)
        owned_fossils = next(
            (s.quantity for s in snap.stacks if s.item_key == "fossil_in_stone"), 0
        )
        if owned_fossils < 1:
            raise PlayerError("tu n'as pas de fossile dans la pierre")
        replicas = fossil_replicas(self.catalog)
        if not replicas:
            raise PlayerError("aucune réplique n'est disponible")
        owned = snap.owned_keys()
        missing = [it for it in replicas if it.key not in owned]
        pool = missing or replicas
        pick = (rng or random.Random()).choice(pool)
        await self._consume_stack(guild_id, user_id, "fossil_in_stone", 1)
        await self.add_item(guild_id, user_id, pick.key, 1, commit=False)
        await self._conn.commit()
        return pick.key

    async def _consume_stack(
        self, guild_id: int, user_id: int, item_key: str, quantity: int = 1
    ) -> int:
        """Retire `quantity` d'un stack. Recheck. Ne commit pas."""
        async with self._conn.execute(
            """
            SELECT quantity FROM inventory_stacks
            WHERE guild_id = ? AND user_id = ? AND item_key = ?
            """,
            (guild_id, user_id, item_key),
        ) as cur:
            row = await cur.fetchone()
        owned = int(row["quantity"]) if row is not None else 0
        if owned < quantity:
            raise PlayerError("tu n'as pas assez de cet item")
        new_qty = owned - quantity
        if new_qty <= 0:
            await self._conn.execute(
                """
                DELETE FROM inventory_stacks
                WHERE guild_id = ? AND user_id = ? AND item_key = ?
                """,
                (guild_id, user_id, item_key),
            )
            await self._conn.execute(
                """
                DELETE FROM equipped
                WHERE guild_id = ? AND user_id = ? AND item_key = ? AND gear_id IS NULL
                """,
                (guild_id, user_id, item_key),
            )
        else:
            await self._conn.execute(
                """
                UPDATE inventory_stacks SET quantity = ?
                WHERE guild_id = ? AND user_id = ? AND item_key = ?
                """,
                (new_qty, guild_id, user_id, item_key),
            )
        return new_qty

    async def _delete_gear(
        self,
        guild_id: int,
        user_id: int,
        gear_id: int,
        *,
        expected_key: str | None = None,
    ) -> None:
        async with self._conn.execute(
            """
            SELECT id, item_key FROM gear_instances
            WHERE id = ? AND guild_id = ? AND user_id = ?
            """,
            (gear_id, guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise PlayerError("équipement introuvable")
        if expected_key is not None and row["item_key"] != expected_key:
            raise PlayerError("équipement introuvable")
        async with self._conn.execute(
            """
            SELECT 1 FROM equipped
            WHERE guild_id = ? AND user_id = ? AND gear_id = ?
            """,
            (guild_id, user_id, gear_id),
        ) as cur:
            if await cur.fetchone() is not None:
                raise PlayerError("retire cet équipement d'abord")
        deleted = await self._conn.execute(
            "DELETE FROM gear_instances WHERE id = ? AND guild_id = ? AND user_id = ?",
            (gear_id, guild_id, user_id),
        )
        if int(deleted.rowcount or 0) != 1:
            raise PlayerError("équipement introuvable")

    async def _grant_starter(self, guild_id: int, user_id: int) -> None:
        starters = self.catalog.items_by_source("starter", enabled_only=True)
        for item in starters:
            if _is_stackable(item):
                await self._add_stack(guild_id, user_id, item, 1)
                await self._try_auto_equip_stack(guild_id, user_id, item)
            else:
                gear_id = await self._insert_gear(guild_id, user_id, item)
                await self._try_auto_equip_gear(guild_id, user_id, item, gear_id)

    async def _add_stack(self, guild_id: int, user_id: int, item: Item, quantity: int) -> int:
        max_stack = max(1, item.inventory.max_stack)
        current = 0
        async with self._conn.execute(
            """
            SELECT quantity FROM inventory_stacks
            WHERE guild_id = ? AND user_id = ? AND item_key = ?
            """,
            (guild_id, user_id, item.key),
        ) as cur:
            row = await cur.fetchone()
            if row is not None:
                current = int(row["quantity"])
        room = max_stack - current
        if room <= 0:
            return 0
        added = min(quantity, room)
        new_qty = current + added
        await self._conn.execute(
            """
            INSERT INTO inventory_stacks (guild_id, user_id, item_key, quantity)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, item_key)
            DO UPDATE SET quantity = excluded.quantity
            """,
            (guild_id, user_id, item.key, new_qty),
        )
        return added

    async def _insert_gear(self, guild_id: int, user_id: int, item: Item) -> int:
        durability = None
        dur = item.durability
        if dur is not None:
            if dur.max_days is not None:
                durability = dur.max_days
            elif dur.max is not None:
                durability = dur.max
        cur = await self._conn.execute(
            """
            INSERT INTO gear_instances (guild_id, user_id, item_key, durability, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild_id, user_id, item.key, durability, _now()),
        )
        gear_id = cur.lastrowid
        if gear_id is None:
            raise PlayerError("impossible de créer l'instance d'équipement")
        return int(gear_id)

    async def _slot_taken(self, guild_id: int, user_id: int, slot: str) -> bool:
        async with self._conn.execute(
            """
            SELECT 1 FROM equipped
            WHERE guild_id = ? AND user_id = ? AND slot = ?
            """,
            (guild_id, user_id, slot),
        ) as cur:
            return await cur.fetchone() is not None

    async def _try_auto_equip_gear(
        self, guild_id: int, user_id: int, item: Item, gear_id: int
    ) -> None:
        slot = item.equipment.slot if item.equipment else None
        if slot not in GEAR_SLOTS:
            return
        if await self._slot_taken(guild_id, user_id, slot):
            return
        await self._conn.execute(
            """
            INSERT INTO equipped (guild_id, user_id, slot, gear_id, item_key)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (guild_id, user_id, slot, gear_id),
        )

    async def _try_auto_equip_stack(self, guild_id: int, user_id: int, item: Item) -> None:
        slot = item.equipment.slot if item.equipment else None
        if slot != BAIT_SLOT:
            return
        if await self._slot_taken(guild_id, user_id, slot):
            return
        await self._conn.execute(
            """
            INSERT INTO equipped (guild_id, user_id, slot, gear_id, item_key)
            VALUES (?, ?, ?, NULL, ?)
            """,
            (guild_id, user_id, slot, item.key),
        )

    async def _fetch_player_row(self, guild_id: int, user_id: int) -> Optional[aiosqlite.Row]:
        async with self._conn.execute(
            "SELECT * FROM players WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cur:
            return await cur.fetchone()

    async def _settle_travel(
        self, guild_id: int, user_id: int, row: aiosqlite.Row
    ) -> tuple[aiosqlite.Row, str | None]:
        dest = row["travel_dest"]
        arrives = row["travel_arrives_at"]
        if not dest or not arrives:
            return row, None
        remaining = travel_remaining_s(arrives)
        if remaining is None or remaining > 0:
            return row, None
        await self._conn.execute(
            """
            UPDATE players
            SET milieu_key = ?, travel_dest = NULL, travel_arrives_at = NULL
            WHERE guild_id = ? AND user_id = ?
            """,
            (dest, guild_id, user_id),
        )
        await self._conn.commit()
        settled = await self._fetch_player_row(guild_id, user_id)
        return (settled if settled is not None else row), dest

    async def _tick_gear_age(self, guild_id: int, user_id: int) -> None:
        now = datetime.now(timezone.utc)
        async with self._conn.execute(
            """
            SELECT id, item_key, durability, created_at FROM gear_instances
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ) as cur:
            rows = await cur.fetchall()
        changed = False
        for row in rows:
            try:
                item = self.catalog.get_item(str(row["item_key"]))
            except CatalogError:
                continue
            dur = item.durability
            if dur is None or dur.loss_trigger != "real_time" or dur.max_days is None:
                continue
            created = parse_iso(row["created_at"])
            if created is None:
                continue
            if (now - created).total_seconds() < float(dur.max_days) * 86400:
                continue
            current = row["durability"]
            if current is not None and int(current) <= 0:
                continue
            await self._conn.execute(
                "UPDATE gear_instances SET durability = 0 WHERE id = ?",
                (int(row["id"]),),
            )
            await self._conn.execute(
                "DELETE FROM equipped WHERE guild_id = ? AND user_id = ? AND gear_id = ?",
                (guild_id, user_id, int(row["id"])),
            )
            changed = True
        if changed:
            await self._conn.commit()

    async def _wear_hooked_attempt(self, guild_id: int, user_id: int) -> bool:
        snap = await self.snapshot(guild_id, user_id)
        hook = snap.equipped.get("hook")
        if hook is None or hook.gear is None:
            return False
        inst = hook.gear
        try:
            item = self.catalog.get_item(inst.item_key)
        except CatalogError:
            return False
        dur = item.durability
        if dur is None or dur.loss_trigger != "hooked_attempt":
            return False
        current = 0 if inst.durability is None else int(inst.durability)
        new = max(0, current - 1)
        await self._conn.execute(
            "UPDATE gear_instances SET durability = ? WHERE id = ? AND guild_id = ? AND user_id = ?",
            (new, inst.id, guild_id, user_id),
        )
        broke = new <= 0
        if broke:
            await self._conn.execute(
                "DELETE FROM equipped WHERE guild_id = ? AND user_id = ? AND slot = ?",
                (guild_id, user_id, "hook"),
            )
        await self._conn.commit()
        return broke

    async def _tick_energy(
        self, guild_id: int, user_id: int
    ) -> tuple[Optional[aiosqlite.Row], str | None]:
        row = await self._fetch_player_row(guild_id, user_id)
        if row is None:
            return None, None
        await self._tick_gear_age(guild_id, user_id)
        row, arrived = await self._settle_travel(guild_id, user_id, row)
        now = datetime.now(timezone.utc)
        until = parse_iso(row["energy_bonus_until"])
        pct = float(row["energy_bonus_pct"] or 0)
        active = bonus_pct_at(pct, until, now)
        if active <= 0:
            pct = 0.0
            until = None
        base_max = int(row["energy_max"])
        eff_max = effective_energy_max(base_max, pct, until, now)
        updated = parse_iso(row["energy_updated_at"])
        energy, new_updated = regen_energy(
            int(row["energy"]),
            eff_max,
            updated,
            now,
            float(self.catalog.game.player.energy_regen_per_hour),
        )
        until_s = until.isoformat() if until is not None else None
        await self._conn.execute(
            """
            UPDATE players
            SET energy = ?, energy_updated_at = ?, energy_bonus_pct = ?, energy_bonus_until = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (energy, new_updated.isoformat(), pct, until_s, guild_id, user_id),
        )
        await self._conn.commit()
        return await self._fetch_player_row(guild_id, user_id), arrived

    def _item(self, item_key: str) -> Item:
        try:
            return self.catalog.get_item(item_key)
        except CatalogError as exc:
            raise PlayerError(f"item inconnu : {item_key!r}") from exc


async def open_store(path: Path | str, catalog: Catalog) -> PlayerStore:
    conn = await connect_db(path)
    return PlayerStore(conn, catalog)
