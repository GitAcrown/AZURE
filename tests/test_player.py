"""Tests du store joueur AZURE (sans Discord)."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

from common.catalog import load_catalog
from common.fishing import Specimen, weather_energy_extra
from common.player import PlayerError, open_store
from common.world import weather_at

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

GUILD_A = 100
GUILD_B = 200
USER = 42


def _cast_cost(catalog, guild_id: int = GUILD_A, milieu: str = "ocean") -> int:
    weather = weather_at(guild_id, milieu, datetime.now(timezone.utc), catalog.game.world)
    extra = weather_energy_extra(catalog, weather.key, ignore=False)
    return int(catalog.game.fishing.cast_energy_cost) + extra


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(ASSETS)


def test_get_or_create_starter_kit(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            snap = await store.get_or_create(GUILD_A, USER)
            assert snap.created is True
            assert snap.energy == 100
            assert snap.energy_max == 100
            assert snap.money == 0
            assert snap.milieu_key is None
            keys = {g.item_key for g in snap.gear}
            assert keys == {"coastal_rod", "widewater_rod", "net"}
            assert all(g.durability is None for g in snap.gear)
            tool = snap.equipped["tool"]
            assert tool.gear is not None
            assert tool.gear.item_key == "coastal_rod"
            assert tool.gear.durability is None
            assert snap.owned_keys() == {"coastal_rod", "widewater_rod", "net"}
            assert snap.dex_found == 0
            assert snap.dex_total == 114
            assert snap.fish_carry == 0
            assert snap.fish_carry_max == 5
            assert snap.creature_carry == 0
            assert snap.creature_carry_max == 5
        finally:
            await store.close()

    _run(body())


def test_second_get_or_create_does_not_duplicate_rod(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            first = await store.get_or_create(GUILD_A, USER)
            second = await store.get_or_create(GUILD_A, USER)
            assert second.created is False
            assert len(second.gear) == 3
            assert {g.id for g in second.gear} == {g.id for g in first.gear}
        finally:
            await store.close()

    _run(body())


def test_guild_isolation(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            a = await store.get_or_create(GUILD_A, USER)
            b = await store.get_or_create(GUILD_B, USER)
            assert a.created is True
            assert b.created is True
            assert a.gear[0].id != b.gear[0].id
            await store.add_money(GUILD_A, USER, 50)
            a2 = await store.snapshot(GUILD_A, USER)
            b2 = await store.snapshot(GUILD_B, USER)
            assert a2.money == 50
            assert b2.money == 0
        finally:
            await store.close()

    _run(body())


def test_stackable_vs_unique(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            await store.get_or_create(GUILD_A, USER)
            added = await store.add_item(GUILD_A, USER, "bread", 3)
            assert added == 3
            snap = await store.snapshot(GUILD_A, USER)
            bread = next(s for s in snap.stacks if s.item_key == "bread")
            assert bread.quantity == 3
            assert len(snap.gear) == 3

            await store.add_item(GUILD_A, USER, "coastal_rod", 1)
            snap = await store.snapshot(GUILD_A, USER)
            assert len(snap.gear) == 4
            assert sum(1 for g in snap.gear if g.item_key == "coastal_rod") == 2
        finally:
            await store.close()

    _run(body())


def test_unknown_item_raises(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            with pytest.raises(PlayerError, match="item inconnu"):
                await store.add_item(GUILD_A, USER, "no_such_item", 1)
        finally:
            await store.close()

    _run(body())


def test_reset_player_then_recreate_starter(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            first = await store.get_or_create(GUILD_A, USER)
            await store.add_item(GUILD_A, USER, "bread", 2)
            await store.add_money(GUILD_A, USER, 80)
            old_id = first.gear[0].id
            await store.reset_player(GUILD_A, USER)
            with pytest.raises(PlayerError, match="introuvable"):
                await store.snapshot(GUILD_A, USER)
            again = await store.get_or_create(GUILD_A, USER)
            assert again.created is True
            assert again.money == 0
            assert again.stacks == []
            assert len(again.gear) == 3
            assert {g.item_key for g in again.gear} == {"coastal_rod", "widewater_rod", "net"}
            assert again.gear[0].id != old_id
            assert all(g.durability is None for g in again.gear)
        finally:
            await store.close()

    _run(body())


def test_energy_clamped(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            await store.get_or_create(GUILD_A, USER)
            assert await store.set_energy(GUILD_A, USER, 40) == 40
            assert await store.set_energy(GUILD_A, USER, 999) == 100
            assert await store.set_energy(GUILD_A, USER, -10) == 0
        finally:
            await store.close()

    _run(body())


def test_set_milieu(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            snap = await store.get_or_create(GUILD_A, USER)
            assert snap.milieu_key is None
            changed, key = await store.set_milieu(GUILD_A, USER, "ocean")
            assert changed is True
            assert key == "ocean"
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.milieu_key == "ocean"
            changed, key = await store.set_milieu(GUILD_A, USER, "ocean")
            assert changed is False
            assert key == "ocean"
            changed, key = await store.set_milieu(GUILD_A, USER, "pond")
            assert changed is True
            assert key == "pond"
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.milieu_key == "ocean"
            assert snap.travel_dest == "pond"
            assert snap.travel_arrives_at
            changed, key = await store.set_milieu(GUILD_A, USER, "pond")
            assert changed is False
            past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            await store._conn.execute(
                """
                UPDATE players SET travel_arrives_at = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (past, GUILD_A, USER),
            )
            await store._conn.commit()
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.milieu_key == "pond"
            assert snap.travel_dest is None
            other = await store.get_or_create(GUILD_B, USER)
            assert other.milieu_key is None
            with pytest.raises(PlayerError, match="milieu inconnu"):
                await store.set_milieu(GUILD_A, USER, "swamp")
        finally:
            await store.close()

    _run(body())


def test_equip_swap_and_unequip(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            snap = await store.get_or_create(GUILD_A, USER)
            coastal = next(g for g in snap.gear if g.item_key == "coastal_rod")
            wide = next(g for g in snap.gear if g.item_key == "widewater_rod")
            assert snap.equipped["tool"].gear_id == coastal.id
            slot = await store.equip_gear(GUILD_A, USER, wide.id)
            assert slot == "tool"
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.equipped["tool"].gear_id == wide.id
            assert any(g.id == coastal.id for g in snap.gear)
            await store.unequip(GUILD_A, USER, "tool")
            snap = await store.snapshot(GUILD_A, USER)
            assert "tool" not in snap.equipped
            with pytest.raises(PlayerError, match="déjà vide"):
                await store.unequip(GUILD_A, USER, "tool")
        finally:
            await store.close()

    _run(body())


def test_equip_bait(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            await store.get_or_create(GUILD_A, USER)
            await store.add_item(GUILD_A, USER, "worm_bait", 2)
            slot = await store.equip_bait(GUILD_A, USER, "worm_bait")
            assert slot == "bait"
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.equipped["bait"].item_key == "worm_bait"
            with pytest.raises(PlayerError, match="appât"):
                await store.equip_bait(GUILD_A, USER, "bread")
        finally:
            await store.close()

    _run(body())


def test_consume_bread_and_coffee(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            await store.get_or_create(GUILD_A, USER)
            await store.set_energy(GUILD_A, USER, 40)
            await store.add_item(GUILD_A, USER, "bread", 2)
            energy, eff = await store.consume_item(GUILD_A, USER, "bread")
            assert energy == 55
            assert eff == 100
            snap = await store.snapshot(GUILD_A, USER)
            bread = next(s for s in snap.stacks if s.item_key == "bread")
            assert bread.quantity == 1
            await store.add_item(GUILD_A, USER, "coffee", 1)
            energy, eff = await store.consume_item(GUILD_A, USER, "coffee")
            assert eff == 120
            assert energy == 55
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.energy_max == 120
            assert snap.coffee_minutes is not None
            assert not any(s.item_key == "coffee" for s in snap.stacks)
            with pytest.raises(PlayerError, match="pas cet item"):
                await store.consume_item(GUILD_A, USER, "coffee")
        finally:
            await store.close()

    _run(body())


def test_energy_regen_on_snapshot(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            await store.get_or_create(GUILD_A, USER)
            await store.set_energy(GUILD_A, USER, 50)
            past = (datetime.now(timezone.utc) - timedelta(minutes=9)).isoformat()
            await store._conn.execute(
                "UPDATE players SET energy_updated_at = ? WHERE guild_id = ? AND user_id = ?",
                (past, GUILD_A, USER),
            )
            await store._conn.commit()
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.energy == 53
        finally:
            await store.close()

    _run(body())


def test_cast_energy_bait_and_fishdex(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            await store.get_or_create(GUILD_A, USER)
            with pytest.raises(PlayerError, match="/monde"):
                await store.cast(GUILD_A, USER)
            await store.set_milieu(GUILD_A, USER, "ocean")
            await store.add_item(GUILD_A, USER, "worm_bait", 2)
            await store.equip_bait(GUILD_A, USER, "worm_bait")
            rng = random.Random(1)
            cost = _cast_cost(catalog)
            first = await store.cast(GUILD_A, USER, rng=rng)
            assert first.energy == 100 - cost
            assert first.energy_max == 100
            assert first.catch_count == 1
            assert first.is_new is True
            assert first.length_cm is not None
            assert 10 <= first.length_cm <= 50
            assert first.personal_record is True
            assert first.guild_rank == 1
            assert first.bait_consumed == "worm_bait"
            assert first.snap.dex_found == 1
            bait = next(s for s in first.snap.stacks if s.item_key == "worm_bait")
            assert bait.quantity == 1
            assert "bait" in first.snap.equipped
            second = await store.cast(GUILD_A, USER, rng=random.Random(1))
            assert second.energy == 100 - 2 * cost
            assert second.bait_consumed == "worm_bait"
            assert second.species_key == first.species_key
            assert second.catch_count == 2
            assert second.is_new is False
            assert "bait" not in second.snap.equipped
            assert not any(s.item_key == "worm_bait" for s in second.snap.stacks)
            same = await store.cast(GUILD_A, USER, rng=random.Random(1))
            assert same.bait_consumed is None
            assert same.energy == 100 - 3 * cost
            assert same.snap.dex_found >= 1
            await store.reset_player(GUILD_A, USER)
            again = await store.get_or_create(GUILD_A, USER)
            assert again.dex_found == 0
        finally:
            await store.close()

    _run(body())


def test_cast_requires_tool_and_energy(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            await store.get_or_create(GUILD_A, USER)
            await store.set_milieu(GUILD_A, USER, "ocean")
            await store.unequip(GUILD_A, USER, "tool")
            with pytest.raises(PlayerError, match="/equip"):
                await store.cast(GUILD_A, USER)
            snap = await store.snapshot(GUILD_A, USER)
            coastal = next(g for g in snap.gear if g.item_key == "coastal_rod")
            await store.equip_gear(GUILD_A, USER, coastal.id)
            await store.set_energy(GUILD_A, USER, 3)
            with pytest.raises(PlayerError, match="énergie"):
                await store.cast(GUILD_A, USER)
        finally:
            await store.close()

    _run(body())


def test_begin_cast_does_not_write_dex_until_finish(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            await store.get_or_create(GUILD_A, USER)
            await store.set_milieu(GUILD_A, USER, "ocean")
            pending = await store.begin_cast(GUILD_A, USER, rng=random.Random(1))
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.energy == 100 - _cast_cost(catalog)
            assert snap.dex_found == 0
            assert pending.action_label == "Ferrer"
            assert pending.trap_early is True
            assert pending.milieu_key == "ocean"
            assert pending.tool_key == "coastal_rod"
            assert pending.hook_key is None
            assert pending.bait_key is None
            assert pending.weather_key in {w.key for w in catalog.game.world.weathers}
            result = await store.finish_cast(
                GUILD_A, USER, pending.species_key, bait_consumed=pending.bait_consumed
            )
            assert result.catch_count == 1
            assert result.snap.dex_found == 1
            rows = await store.list_dex(GUILD_A, USER)
            assert pending.species_key in rows
            tops = await store.list_guild_records(GUILD_A)
            assert tops
            assert tops[0][0] == pending.species_key
        finally:
            await store.close()

    _run(body())


def test_hook_wears_and_forced_loot(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "wear.db", catalog)
        try:
            await store.get_or_create(GUILD_A, USER)
            await store.set_milieu(GUILD_A, USER, "ocean")
            await store.add_item(GUILD_A, USER, "big_hook")
            snap = await store.snapshot(GUILD_A, USER)
            hook = next(g for g in snap.gear if g.item_key == "big_hook")
            assert hook.durability == 140
            await store.equip_gear(GUILD_A, USER, hook.id)

            class _Always:
                def random(self) -> float:
                    return 0.0

                def choices(self, pop, weights=None, k=1):
                    return [pop[0]]

                def uniform(self, a, b):
                    return (a + b) / 2

            result = await store.cast(GUILD_A, USER, rng=_Always())
            snap = await store.snapshot(GUILD_A, USER)
            worn = next(g for g in snap.gear if g.item_key == "big_hook")
            assert worn.durability == 139
            assert result.loot_key is not None
            assert catalog.get_item(result.loot_key).category != "waste"
        finally:
            await store.close()

    _run(body())


def test_preview_cast_does_not_write_dex(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            await store.get_or_create(GUILD_A, USER)
            preview = await store.preview_cast(
                GUILD_A,
                USER,
                "parrot_fish",
                specimen=Specimen(40.0, 1.5),
                energy=90,
                energy_max=100,
            )
            assert preview.catch_count == 1
            assert preview.is_new is True
            assert preview.personal_record is True
            assert preview.guild_rank == 1
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.dex_found == 0
            async with store._conn.execute(
                "SELECT COUNT(*) AS n FROM caught_specimens WHERE guild_id = ? AND user_id = ?",
                (GUILD_A, USER),
            ) as cur:
                row = await cur.fetchone()
            assert int(row["n"]) == 0
            result = await store.finish_cast(
                GUILD_A,
                USER,
                "parrot_fish",
                preview=preview,
                specimen=Specimen(40.0, 1.5),
                energy=90,
                energy_max=100,
            )
            assert result.catch_count == 1
            assert result.guild_rank == 1
            rows = await store.list_dex(GUILD_A, USER)
            assert "parrot_fish" in rows
        finally:
            await store.close()

    _run(body())


def test_guild_records_top3_medals(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            gold = await store.finish_cast(
                GUILD_A, 42, "parrot_fish", specimen=Specimen(50.0, 2.0)
            )
            assert gold.personal_record is True
            assert gold.guild_rank == 1
            silver = await store.finish_cast(
                GUILD_A, 43, "parrot_fish", specimen=Specimen(40.0, 1.5)
            )
            assert silver.guild_rank == 2
            bronze = await store.finish_cast(
                GUILD_A, 44, "parrot_fish", specimen=Specimen(30.0, 1.0)
            )
            assert bronze.guild_rank == 3
            fourth = await store.finish_cast(
                GUILD_A, 45, "parrot_fish", specimen=Specimen(20.0, 0.5)
            )
            assert fourth.guild_rank is None
            usurper = await store.finish_cast(
                GUILD_A, 45, "parrot_fish", specimen=Specimen(60.0, 3.0)
            )
            assert usurper.personal_record is True
            assert usurper.guild_rank == 1
            worse = await store.finish_cast(
                GUILD_A, 45, "parrot_fish", specimen=Specimen(10.0, 0.1)
            )
            assert worse.personal_record is False
            assert worse.guild_rank is None
            await store.reset_player(GUILD_A, 45)
            async with store._conn.execute(
                """
                SELECT user_id FROM guild_records
                WHERE guild_id = ? AND species_key = ?
                ORDER BY length_cm DESC
                """,
                (GUILD_A, "parrot_fish"),
            ) as cur:
                ids = [int(r["user_id"]) for r in await cur.fetchall()]
            assert 45 not in ids
            assert ids[0] == 42
        finally:
            await store.close()

    _run(body())


def test_guild_records_migrates_old_primary_key(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        db = tmp_path / "old.db"
        conn = await aiosqlite.connect(db)
        await conn.execute(
            """
            CREATE TABLE guild_records (
                guild_id INTEGER NOT NULL,
                species_key TEXT NOT NULL,
                length_cm REAL NOT NULL,
                weight_kg REAL NOT NULL,
                user_id INTEGER NOT NULL,
                caught_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, species_key)
            )
            """
        )
        await conn.execute(
            """
            INSERT INTO guild_records (
                guild_id, species_key, length_cm, weight_kg, user_id, caught_at
            )
            VALUES (100, 'parrot_fish', 40.0, 1.2, 42, 'now')
            """
        )
        await conn.commit()
        await conn.close()
        store = await open_store(db, catalog)
        try:
            async with store._conn.execute("PRAGMA table_info(guild_records)") as cur:
                rows = await cur.fetchall()
            pk = [str(r[1]) for r in sorted(rows, key=lambda r: int(r[5] or 0)) if int(r[5] or 0) > 0]
            assert pk == ["guild_id", "species_key", "user_id"]
            async with store._conn.execute(
                "SELECT user_id, length_cm FROM guild_records"
            ) as cur:
                row = await cur.fetchone()
            assert int(row["user_id"]) == 42
            assert float(row["length_cm"]) == 40.0
        finally:
            await store.close()

    _run(body())


async def _caught_count(store, guild_id: int, user_id: int) -> int:
    async with store._conn.execute(
        "SELECT COUNT(*) AS n FROM caught_specimens WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    return int(row["n"]) if row is not None else 0


def test_keep_specimen_when_room(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            result = await store.finish_cast(
                GUILD_A, USER, "parrot_fish", specimen=Specimen(32.0, 0.4)
            )
            assert result.kept is True
            assert result.carry_used == 1
            assert result.carry_max == 5
            assert await _caught_count(store, GUILD_A, USER) == 1
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.fish_carry == 1
            assert snap.fish_carry_max == 5
            assert snap.creature_carry == 0
            caught = await store.list_caught(GUILD_A, USER)
            assert len(caught) == 1
            assert caught[0].species_key == "parrot_fish"
            assert caught[0].length_cm == 32.0
            assert caught[0].weight_kg == 0.4
        finally:
            await store.close()

    _run(body())


def test_full_bag_still_writes_dex(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            for i in range(5):
                kept = await store.finish_cast(
                    GUILD_A,
                    USER,
                    "parrot_fish",
                    specimen=Specimen(10.0 + i, 0.2 + i * 0.1),
                )
                assert kept.kept is True
            full = await store.finish_cast(
                GUILD_A, USER, "parrot_fish", specimen=Specimen(40.0, 1.5)
            )
            assert full.kept is False
            assert full.carry_used == 5
            assert full.carry_max == 5
            assert full.catch_count == 6
            assert full.is_new is False
            assert await _caught_count(store, GUILD_A, USER) == 5
            rows = await store.list_dex(GUILD_A, USER)
            assert rows["parrot_fish"].catch_count == 6
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.dex_found == 1
            assert snap.fish_carry == 5
            creature = await store.finish_cast(
                GUILD_A, USER, "shrimp", specimen=Specimen(8.0, 0.05)
            )
            assert creature.kept is True
            assert creature.carry_used == 1
            assert creature.carry_max == 5
            assert await _caught_count(store, GUILD_A, USER) == 6
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.fish_carry == 5
            assert snap.creature_carry == 1
        finally:
            await store.close()

    _run(body())


def test_bucket_and_basket_carry_bonus(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            await store.get_or_create(GUILD_A, USER)
            await store.add_item(GUILD_A, USER, "bucket", 1)
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.fish_carry_max == 8
            assert snap.creature_carry_max == 5
            for i in range(6):
                result = await store.finish_cast(
                    GUILD_A,
                    USER,
                    "parrot_fish",
                    specimen=Specimen(12.0 + i, 0.3),
                )
                assert result.kept is True
            assert result.carry_used == 6
            assert result.carry_max == 8
            await store.add_item(GUILD_A, USER, "basket", 1)
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.fish_carry_max == 8
            assert snap.creature_carry_max == 8
            shrimp = await store.finish_cast(
                GUILD_A, USER, "shrimp", specimen=Specimen(6.0, 0.04)
            )
            assert shrimp.kept is True
            assert shrimp.carry_max == 8
            shell = await store.finish_cast(
                GUILD_A, USER, "pink_conch", specimen=Specimen(14.0, 0.3)
            )
            assert shell.kept is True
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.creature_carry == 2
            assert snap.creature_carry_max == 8
        finally:
            await store.close()

    _run(body())


def test_release_caught_frees_slot(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            for i in range(5):
                await store.finish_cast(
                    GUILD_A,
                    USER,
                    "parrot_fish",
                    specimen=Specimen(20.0 + i, 0.5),
                )
            full = await store.finish_cast(
                GUILD_A, USER, "parrot_fish", specimen=Specimen(50.0, 2.0)
            )
            assert full.kept is False
            caught = await store.list_caught(GUILD_A, USER)
            assert len(caught) == 5
            released = await store.release_caught(GUILD_A, USER, caught[0].id)
            assert released.species_key == "parrot_fish"
            snap = await store.snapshot(GUILD_A, USER)
            assert snap.fish_carry == 4
            rows = await store.list_dex(GUILD_A, USER)
            assert rows["parrot_fish"].catch_count == 6
            again = await store.finish_cast(
                GUILD_A, USER, "parrot_fish", specimen=Specimen(11.0, 0.2)
            )
            assert again.kept is True
            assert again.carry_used == 5
            assert await _caught_count(store, GUILD_A, USER) == 5
        finally:
            await store.close()

    _run(body())


def test_reset_player_clears_caught_specimens(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            await store.finish_cast(
                GUILD_A, USER, "parrot_fish", specimen=Specimen(30.0, 1.0)
            )
            await store.finish_cast(
                GUILD_A, USER, "shrimp", specimen=Specimen(5.0, 0.02)
            )
            assert await _caught_count(store, GUILD_A, USER) == 2
            await store.reset_player(GUILD_A, USER)
            assert await _caught_count(store, GUILD_A, USER) == 0
            async with store._conn.execute(
                "SELECT COUNT(*) AS n FROM fishdex WHERE guild_id = ? AND user_id = ?",
                (GUILD_A, USER),
            ) as cur:
                row = await cur.fetchone()
            assert int(row["n"]) == 0
        finally:
            await store.close()

    _run(body())


def test_collection_gems_unlock_and_sac_split(catalog, tmp_path: Path) -> None:
    from cogs.azure.views import _collection_block, _inventory_parts

    async def body() -> None:
        store = await open_store(tmp_path / "a.db", catalog)
        try:
            snap = await store.get_or_create(GUILD_A, USER)
            text = _collection_block(catalog, snap)
            assert "**Dex** · 0/114" in text
            assert "**Gemmes** · 0/7" in text
            assert "**Fossiles** · 0/5" in text
            await store.add_item(GUILD_A, USER, "red_gem", 2)
            await store.add_item(GUILD_A, USER, "bread", 1)
            await store.add_item(GUILD_A, USER, "fossil_plaster_a", 1)
            snap = await store.snapshot(GUILD_A, USER)
            text = _collection_block(catalog, snap)
            assert "**Gemmes** · 1/7" in text
            assert "**Fossiles** · 1/5" in text
            items = _inventory_parts(catalog, snap, collectibles=False)
            coll = _inventory_parts(catalog, snap, collectibles=True)
            assert any("Pain" in p or "bread" in p.lower() for p in items)
            assert any("Gemme" in p for p in coll)
            assert all("Gemme" not in p for p in items)
        finally:
            await store.close()

    _run(body())
