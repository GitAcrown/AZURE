"""Village AZURE : présence, prix, ventes, Oz, Gaia, reset serveur."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from common.catalog import load_catalog
from common.fishing import Specimen
from common.player import PlayerError, open_store
from common.village import (
    ANNOUNCE_KINDS,
    announcement_remaining_label,
    apply_named_mult,
    bargain_modifier,
    build_announcement_modifier,
    env_quality_mult,
    focus_talk_board,
    environment_is_good,
    environment_is_great,
    environment_is_poor,
    environment_pct,
    infer_modifier_kind,
    modifier_label,
    npc_can_bargain,
    npc_portrait_filename,
    npc_role_label,
    passeur_price,
    present_npcs,
    talk_select_description,
    skull_score,
    specimen_price,
    travel_duration_s,
    travel_remaining_s,
    village_bucket,
    walk_minutes,
    walk_time_mult,
)

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

GUILD = 7001
USER = 88
PARIS = ZoneInfo("Europe/Paris")
DAY = datetime(2026, 6, 15, 12, 0, tzinfo=PARIS)
NIGHT = datetime(2026, 6, 15, 23, 0, tzinfo=PARIS)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(ASSETS)


def test_passeur_price_prorata(catalog) -> None:
    full = catalog.game.village.travel_cost
    total = float(travel_duration_s(catalog))
    assert passeur_price(catalog, remaining_s=None) == full
    assert passeur_price(catalog, remaining_s=0) == 0
    assert passeur_price(catalog, remaining_s=total) == full
    assert passeur_price(catalog, remaining_s=total / 2) == max(1, round(full * 0.5))


def test_compass_shortens_walk(catalog, tmp_path: Path) -> None:
    assert travel_duration_s(catalog) == 1800
    assert walk_minutes(catalog) == 30
    assert catalog.get_item("compass").effects.get("walk_time_mult") == 0.2

    async def body() -> None:
        store = await open_store(tmp_path / "compass.db", catalog)
        try:
            await store.get_or_create(GUILD, USER)
            await store.set_milieu(GUILD, USER, "ocean")
            snap = await store.snapshot(GUILD, USER)
            assert walk_time_mult(catalog, snap) == 1.0
            await store.add_item(GUILD, USER, "compass", 1)
            snap = await store.snapshot(GUILD, USER)
            compass = next(g for g in snap.gear if g.item_key == "compass")
            await store.equip_gear(GUILD, USER, compass.id)
            snap = await store.snapshot(GUILD, USER)
            assert walk_time_mult(catalog, snap) == 0.2
            assert travel_duration_s(catalog, snap=snap) == 360
            assert walk_minutes(catalog, snap) == 6
            await store.set_milieu(GUILD, USER, "pond")
            snap = await store.snapshot(GUILD, USER)
            rem = travel_remaining_s(snap.travel_arrives_at)
            assert rem is not None
            assert 350 <= rem <= 361
        finally:
            await store.close()

    _run(body())


def test_bargain_modifier_and_sanitize(catalog) -> None:
    from common.village.talk import sanitize_talk

    dan = catalog.get_npc("dan")
    agathe = catalog.get_npc("agathe")
    oz = catalog.get_npc("oz")
    assert npc_can_bargain(dan)
    assert npc_can_bargain(agathe)
    assert not npc_can_bargain(oz)
    assert not npc_can_bargain(catalog.get_npc("esmer"))
    shop = bargain_modifier(catalog, dan)
    assert infer_modifier_kind(shop) == "bargain"
    assert apply_named_mult(100, [shop], "buy_mult") == 95
    assert "négociation" in modifier_label(shop)
    sale = bargain_modifier(catalog, agathe)
    assert apply_named_mult(100, [sale], "sell_mult") == 105
    species = catalog.get_species("parrot_fish")
    base = specimen_price(catalog, species, 30.0, 1.04)
    boosted = specimen_price(catalog, species, 30.0, 1.04, modifiers=[sale])
    assert boosted > base
    yes = sanitize_talk(
        {
            "reponse": "(Souffle.) Bon, un tout petit peu.",
            "intent": "none",
            "bargain": True,
        },
        catalog,
        dan,
    )
    assert yes["bargain"] is True
    again = sanitize_talk(
        {"reponse": "Encore.", "intent": "none", "bargain": True},
        catalog,
        dan,
        already_bargained=True,
    )
    assert again["bargain"] is False
    mute = sanitize_talk(
        {"reponse": "(Hoche.)", "intent": "none", "bargain": True},
        catalog,
        oz,
    )
    assert mute["bargain"] is False


def test_bargain_persists_and_cuts_buy_price(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "bargain.db", catalog)
        try:
            dan = catalog.get_npc("dan")
            await store.get_or_create(GUILD, USER)
            bucket = village_bucket(catalog)
            assert (
                await store.get_village_bargain(GUILD, USER, "dan", bucket=bucket)
                is None
            )
            granted = await store.set_village_bargain(
                GUILD, USER, dan, bucket=bucket
            )
            assert granted is True
            assert await store.set_village_bargain(GUILD, USER, dan, bucket=bucket) is False
            await store.set_village_focus(GUILD, USER, "dan", bucket)
            fare = catalog.get_item("bread").economy.buy_price
            assert fare is not None
            expected = apply_named_mult(int(fare), [bargain_modifier(catalog, dan)], "buy_mult")
            await store.add_money(GUILD, USER, expected + 5)
            paid, money = await store.buy_item(
                GUILD, USER, "bread", 1, seller_key="dan"
            )
            assert paid == expected
            assert paid < int(fare)
            assert money == 5
        finally:
            await store.close()

    _run(body())


def test_concurrent_buy_does_not_overdraw(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "race-buy.db", catalog)
        try:
            await store.get_or_create(GUILD, USER)
            price = int(catalog.get_item("bread").economy.buy_price or 0)
            await store.add_money(GUILD, USER, price)
            first, second = await asyncio.gather(
                store.buy_item(GUILD, USER, "bread", 1),
                store.buy_item(GUILD, USER, "bread", 1),
                return_exceptions=True,
            )
            results = [first, second]
            oks = [x for x in results if not isinstance(x, BaseException)]
            errs = [x for x in results if isinstance(x, BaseException)]
            assert len(oks) == 1
            assert len(errs) == 1
            assert isinstance(errs[0], PlayerError)
            assert "argent" in str(errs[0])
            snap = await store.snapshot(GUILD, USER)
            assert snap.money == 0
            bread = next(s for s in snap.stacks if s.item_key == "bread")
            assert bread.quantity == 1
        finally:
            await store.close()

    _run(body())
    empty = present_npcs(catalog, GUILD, skulls=0, bucket=1, dt=DAY)
    roles = [n.role for n in empty]
    shops = [n for n in empty if n.role == "shop"]
    assert roles.count("shop") == 3
    assert {n.shop_mode for n in shops} == {"sell", "buy"}
    assert roles.count("repair") == 2
    assert roles.count("travel") == 2
    assert "gaia" in {n.key for n in empty}
    assert "esmer" in {n.key for n in empty}
    assert "oz" not in {n.key for n in empty}
    assert {n.key for n in shops if n.shop_mode == "sell"} == {"dan", "joel"}
    assert {n.key for n in shops if n.shop_mode == "buy"} == {"agathe"}
    assert {n.key for n in empty if n.role == "repair"} == {"maurice", "patrick"}
    assert {n.key for n in empty if n.role == "travel"} <= {"gabriel", "inti", "hedwig"}
    assert len({n.key for n in empty if n.role == "travel"}) == 2

    with_oz = present_npcs(catalog, GUILD, skulls=10, bucket=1, dt=DAY)
    assert "oz" in {n.key for n in with_oz}

    same = present_npcs(catalog, GUILD, skulls=0, bucket=1, dt=DAY)
    assert [n.key for n in same] == [n.key for n in empty]

    night = present_npcs(catalog, GUILD, skulls=0, bucket=1, dt=NIGHT)
    night_roles = [n.role for n in night]
    assert len([n for n in night if n.shop_mode == "sell"]) == 1
    assert night_roles.count("repair") == 1
    assert night_roles.count("travel") == 1
    assert "gaia" in {n.key for n in night}
    assert "esmer" in {n.key for n in night}


def test_roster_is_deterministic_per_bucket(catalog) -> None:
    a = [n.key for n in present_npcs(catalog, GUILD, skulls=0, bucket=3, dt=DAY)]
    b = [n.key for n in present_npcs(catalog, GUILD, skulls=0, bucket=3, dt=DAY)]
    assert a == b
    other_guild = [n.key for n in present_npcs(catalog, GUILD + 1, skulls=0, bucket=3, dt=DAY)]
    # Même palier, autre serveur : le tirage shop/repair peut diverger.
    assert len(other_guild) == len(a)


def test_specimen_price_size_and_weight(catalog) -> None:
    species = catalog.get_species("parrot_fish")
    mid = specimen_price(catalog, species, 30.0, 1.04)
    assert mid == 12
    low = specimen_price(catalog, species, 10.0, 0.08)
    assert low == 6
    high = specimen_price(catalog, species, 50.0, 2.0)
    assert high == 18
    boosted = specimen_price(
        catalog,
        species,
        30.0,
        1.04,
        modifiers=[{"min_weight_kg": 0.5, "mult": 1.2}],
    )
    assert boosted == 14
    skipped = specimen_price(
        catalog,
        species,
        30.0,
        1.04,
        modifiers=[{"min_weight_kg": 5, "mult": 1.2}],
    )
    assert skipped == 12


def test_gaia_portraits_follow_env_score(catalog) -> None:
    gaia = catalog.get_npc("gaia")
    assert environment_is_good(catalog, 49) is False
    assert environment_is_good(catalog, 50) is True
    assert environment_pct(catalog, 50) == 50
    assert environment_is_great(catalog, 75) is False
    assert environment_is_great(catalog, 76) is True
    assert environment_is_poor(catalog, 25) is False
    assert environment_is_poor(catalog, 24) is True
    assert env_quality_mult(catalog, 80) == 1.4
    assert env_quality_mult(catalog, 50) == 1.0
    assert env_quality_mult(catalog, 10) == 0.6
    assert npc_portrait_filename(gaia, env_good=False) == "portrait11.png"
    assert npc_portrait_filename(gaia, env_good=True) == "portrait10.png"
    oz = catalog.get_npc("oz")
    assert npc_portrait_filename(oz, env_good=False) == "portrait13.png"
    assert npc_portrait_filename(oz, env_good=True) == "portrait12.png"


def test_overfish_lowers_environment(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "overfish.db", catalog)
        try:
            await store.get_or_create(GUILD, USER)
            await store.set_milieu(GUILD, USER, "ocean")
            start = await store.environment_score(GUILD)
            assert start == 50
            cap = catalog.game.village.overfish_per_bucket
            for _ in range(cap):
                await store.finish_cast(
                    GUILD, USER, "parrot_fish", specimen=Specimen(30.0, 1.04)
                )
            assert await store.environment_score(GUILD) == start
            await store.finish_cast(
                GUILD, USER, "parrot_fish", specimen=Specimen(30.0, 1.04)
            )
            assert await store.environment_score(GUILD) == start - 1
        finally:
            await store.close()

    _run(body())


def test_sell_buy_repair_oz_and_reset(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "village.db", catalog)
        try:
            await store.get_or_create(GUILD, USER)
            await store.finish_cast(
                GUILD, USER, "parrot_fish", specimen=Specimen(30.0, 1.04)
            )
            caught = await store.list_caught(GUILD, USER)
            assert len(caught) == 1
            price, key, money = await store.sell_specimen(GUILD, USER, caught[0].id)
            assert key == "parrot_fish"
            assert price == 12
            assert money == 12
            assert await store.list_caught(GUILD, USER) == []

            await store.add_item(GUILD, USER, "broken_bottle", 1)
            sold, money, env_gain = await store.sell_item(GUILD, USER, "broken_bottle")
            assert sold == 1
            assert env_gain == 1
            assert await store.environment_score(GUILD) == 51
            assert money == 13

            await store.add_money(GUILD, USER, 100)
            paid, money = await store.buy_item(GUILD, USER, "bread", 1)
            bread = catalog.get_item("bread")
            assert paid == int(bread.economy.buy_price or 0)
            snap = await store.snapshot(GUILD, USER)
            assert any(s.item_key == "bread" for s in snap.stacks)

            await store.add_item(GUILD, USER, "lantern", 1)
            snap = await store.snapshot(GUILD, USER)
            lantern = next(g for g in snap.gear if g.item_key == "lantern")
            await store._conn.execute(
                "UPDATE gear_instances SET durability = 1 WHERE id = ?",
                (lantern.id,),
            )
            await store._conn.commit()
            await store.add_money(GUILD, USER, 200)
            cost, _money = await store.repair_gear(GUILD, USER, lantern.id)
            assert cost == 55
            snap = await store.snapshot(GUILD, USER)
            repaired = next(g for g in snap.gear if g.id == lantern.id)
            assert repaired.durability == 30

            snap = await store.snapshot(GUILD, USER)
            assert skull_score(catalog, snap) == 0
            await store.add_item(GUILD, USER, "normal_skull", 9)
            snap = await store.snapshot(GUILD, USER)
            assert skull_score(catalog, snap) == 9
            assert "oz" not in {
                n.key for n in present_npcs(
                    catalog, GUILD, skulls=skull_score(catalog, snap), bucket=1, dt=DAY
                )
            }
            await store.add_item(GUILD, USER, "normal_skull", 1)
            snap = await store.snapshot(GUILD, USER)
            assert skull_score(catalog, snap) == 10
            assert "oz" in {
                n.key for n in present_npcs(
                    catalog, GUILD, skulls=skull_score(catalog, snap), bucket=1, dt=DAY
                )
            }

            await store.add_item(GUILD, USER, "golden_skull", 2)
            snap = await store.snapshot(GUILD, USER)
            assert skull_score(catalog, snap) == 20

            await store.add_item(GUILD, USER, "fossil_in_stone", 1)
            replica = await store.exchange_fossil(GUILD, USER, rng=__import__("random").Random(0))
            assert replica.startswith("fossil_plaster_")
            snap = await store.snapshot(GUILD, USER)
            assert replica in snap.owned_keys()
            assert not any(s.item_key == "fossil_in_stone" for s in snap.stacks)
            skulls_after = skull_score(catalog, snap)
            assert skulls_after == 20

            await store.post_village_announcement(
                GUILD,
                "dan",
                "Gros poissons bien payés.",
                hours=6,
                modifier={"min_weight_kg": 0.5, "mult": 2.0},
            )
            await store.finish_cast(
                GUILD, USER, "parrot_fish", specimen=Specimen(30.0, 1.04)
            )
            caught = await store.list_caught(GUILD, USER)
            price, _key, _money = await store.sell_specimen(GUILD, USER, caught[0].id)
            assert price == 24

            env_before = await store.environment_score(GUILD)
            anns = await store.list_village_announcements(GUILD)
            assert env_before >= 1
            assert anns
            await store.reset_player(GUILD, USER)
            assert await store.environment_score(GUILD) == env_before
            assert await store.list_village_announcements(GUILD)
            snap = await store.get_or_create(GUILD, USER)
            assert snap.money == 0
            assert skull_score(catalog, snap) == 0
        finally:
            await store.close()

    _run(body())


def test_cannot_sell_gem_or_missing_catch(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "deny.db", catalog)
        try:
            await store.get_or_create(GUILD, USER)
            await store.add_item(GUILD, USER, "red_gem", 1)
            with pytest.raises(PlayerError, match="ne se vend pas"):
                await store.sell_item(GUILD, USER, "red_gem")
            with pytest.raises(PlayerError, match="prise introuvable"):
                await store.sell_specimen(GUILD, USER, 999)
            with pytest.raises(PlayerError, match="fossile"):
                await store.exchange_fossil(GUILD, USER)
        finally:
            await store.close()

    _run(body())


def test_expire_announcements(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "ann.db", catalog)
        try:
            posted = await store.post_village_announcement(
                GUILD,
                "agathe",
                "Bientôt fini.",
                hours=1,
                modifier={"kind": "waste", "waste_mult": 2.0},
            )
            assert posted.npc_key == "agathe"
            assert await store.list_village_announcements(GUILD)
            await store._conn.execute(
                "UPDATE village_announcements SET ends_at = ?",
                (datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat(),),
            )
            await store._conn.commit()
            n = await store.expire_village_announcements()
            assert n == 1
            assert await store.list_village_announcements(GUILD) == []
        finally:
            await store.close()

    _run(body())


def test_seller_stock_and_paid_travel(catalog, tmp_path: Path) -> None:
    from common.fishing import roll_waste
    from common.village import shop_stock
    from common.village.talk import sanitize_talk

    dan = catalog.get_npc("dan")
    joel = catalog.get_npc("joel")
    keys_dan = {it.key for it in shop_stock(catalog, dan)}
    keys_joel = {it.key for it in shop_stock(catalog, joel)}
    assert "bread" in keys_dan
    assert "lantern" not in keys_dan
    assert "lantern" in keys_joel
    assert "bread" not in keys_joel

    cleaned = sanitize_talk(
        {
            "reponse": "Je t'emmène à la mer.",
            "intent": "travel",
            "item_key": "bread",
            "milieu_key": "ocean",
        },
        catalog,
        dan,
    )
    assert cleaned["intent"] == "none"
    assert cleaned["milieu_key"] is None
    assert cleaned["quantity"] == 1

    trio = sanitize_talk(
        {
            "reponse": "Trois pains.",
            "intent": "buy",
            "item_key": "bread",
            "milieu_key": None,
            "display": "stock",
            "board_keys": ["bread"],
            "quantity": 3,
        },
        catalog,
        dan,
    )
    assert trio["intent"] == "buy"
    assert trio["item_key"] == "bread"
    assert trio["quantity"] == 3

    gabriel = catalog.get_npc("gabriel")
    trip = sanitize_talk(
        {
            "reponse": "L'océan, alors.",
            "intent": "travel",
            "item_key": None,
            "milieu_key": "ocean",
        },
        catalog,
        gabriel,
    )
    assert trip["intent"] == "travel"
    assert trip["milieu_key"] == "ocean"

    class _Low:
        def random(self) -> float:
            return 0.0

        def choices(self, pop, weights=None, k=1):
            return [pop[0]]

    junk = roll_waste(catalog, _Low())
    assert junk is not None
    assert junk.category == "waste"

    async def body() -> None:
        store = await open_store(tmp_path / "travel.db", catalog)
        try:
            await store.get_or_create(GUILD, USER)
            with pytest.raises(PlayerError, match="pas assez d'argent"):
                await store.travel_to(GUILD, USER, "ocean")
            fare = catalog.game.village.travel_cost
            await store.add_money(GUILD, USER, fare + 20)
            changed, key, money = await store.travel_to(GUILD, USER, "ocean")
            assert changed is True
            assert key == "ocean"
            assert money == 20
            changed, key, money = await store.travel_to(GUILD, USER, "ocean")
            assert changed is False
            assert money == 20
            await store.set_milieu(GUILD, USER, "pond")
            halfway = (
                datetime.now(timezone.utc)
                + timedelta(seconds=travel_duration_s(catalog) / 2)
            ).isoformat()
            await store._conn.execute(
                """
                UPDATE players SET travel_arrives_at = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (halfway, GUILD, USER),
            )
            await store._conn.commit()
            snap = await store.snapshot(GUILD, USER)
            assert snap.milieu_key == "ocean"
            assert snap.travel_dest == "pond"
            rem = travel_remaining_s(snap.travel_arrives_at)
            assert rem is not None and rem > 0
            expected = passeur_price(catalog, remaining_s=rem)
            assert expected < catalog.game.village.travel_cost
            changed, key, money = await store.travel_to(GUILD, USER, "pond")
            assert changed is True
            assert key == "pond"
            assert money == snap.money - expected
            with pytest.raises(PlayerError, match="rayon"):
                await store.buy_item(GUILD, USER, "lantern", seller_key="dan")
            await store.add_money(GUILD, USER, 20)
            paid, _money = await store.buy_item(GUILD, USER, "bread", seller_key="dan")
            assert paid == 12
        finally:
            await store.close()

    _run(body())


def test_talk_sanitize_display_and_oz(catalog) -> None:
    from common.village.talk import sanitize_talk

    dan = catalog.get_npc("dan")
    shown = sanitize_talk(
        {
            "reponse": "(Hoche la tête.) Le pain, là.",
            "intent": "buy",
            "item_key": "bread",
            "milieu_key": None,
            "display": "stock",
            "board_keys": ["bread", "ocean", "inconnu"],
        },
        catalog,
        dan,
    )
    assert shown["display"] == "stock"
    assert shown["board_keys"] == ["bread"]
    assert shown["intent"] == "buy"
    assert shown["item_key"] == "bread"

    forbidden = sanitize_talk(
        {
            "reponse": "Voici mes destinations.",
            "intent": "none",
            "item_key": None,
            "milieu_key": None,
            "display": "destinations",
            "board_keys": ["ocean"],
        },
        catalog,
        dan,
    )
    assert forbidden["display"] == "none"

    agathe = catalog.get_npc("agathe")
    fish = sanitize_talk(
        {
            "reponse": "Je te prends le perroquet.",
            "intent": "sell",
            "item_key": "parrot_fish",
            "milieu_key": None,
            "display": "purse",
            "board_keys": ["parrot_fish"],
        },
        catalog,
        agathe,
    )
    assert fish["intent"] == "sell"
    assert fish["item_key"] == "parrot_fish"
    assert fish["board_keys"] == ["parrot_fish"]

    junk = sanitize_talk(
        {
            "reponse": "La bouteille, je la prends.",
            "intent": "sell",
            "item_key": "broken_bottle",
            "milieu_key": None,
            "display": "purse",
            "board_keys": ["broken_bottle"],
        },
        catalog,
        agathe,
    )
    assert junk["intent"] == "sell"
    assert junk["item_key"] == "broken_bottle"

    gaia = catalog.get_npc("gaia")
    rates = sanitize_talk(
        {
            "reponse": "(Incline un visage trop lisse.) Neth. La bouteille.",
            "intent": "cleanup",
            "item_key": "broken_bottle",
            "milieu_key": None,
            "display": "env",
            "board_keys": ["broken_bottle", "ocean"],
        },
        catalog,
        gaia,
    )
    assert rates["intent"] == "cleanup"
    assert rates["item_key"] == "broken_bottle"
    assert rates["display"] == "env"
    assert rates["board_keys"] == ["broken_bottle"]

    oz = catalog.get_npc("oz")
    silent = sanitize_talk(
        {
            "reponse": "Salut toi (Tends un fossile.) et encore des mots.",
            "intent": "exchange",
            "item_key": "fossil_in_stone",
            "milieu_key": None,
            "display": "fossils",
            "board_keys": [],
        },
        catalog,
        oz,
    )
    assert silent["reponse"] == "(Tends un fossile.)"
    assert silent["display"] == "fossils"
    assert silent["intent"] == "exchange"

    mute = sanitize_talk(
        {
            "reponse": "Je parle alors que je ne dois pas.",
            "intent": "none",
            "item_key": None,
            "milieu_key": None,
            "display": "none",
            "board_keys": [],
        },
        catalog,
        oz,
    )
    assert mute["reponse"].startswith("(")
    assert mute["reponse"].endswith(")")


def test_announcement_kinds(catalog) -> None:
    assert set(ANNOUNCE_KINDS) >= {
        "sale_weight",
        "sale_length",
        "sale_rarity",
        "sale_ocean",
        "sale_river",
        "sale_pond",
        "shop_buy",
        "travel",
        "repair",
        "waste",
    }
    ocean = build_announcement_modifier("sale_ocean")
    assert infer_modifier_kind(ocean) == "sale_ocean"
    assert "océan" in modifier_label(ocean)
    assert "×" in modifier_label(ocean)
    species = catalog.get_species("parrot_fish")
    base = specimen_price(catalog, species, 30.0, 1.04)
    boosted = specimen_price(catalog, species, 30.0, 1.04, modifiers=[ocean])
    assert boosted > base
    river = build_announcement_modifier("sale_river")
    skipped = specimen_price(catalog, species, 30.0, 1.04, modifiers=[river])
    assert skipped == base
    shop = build_announcement_modifier("shop_buy")
    assert apply_named_mult(100, [shop], "buy_mult") == 80
    travel = build_announcement_modifier("travel")
    assert apply_named_mult(20, [travel], "travel_mult") == 10
    waste = build_announcement_modifier("waste")
    assert apply_named_mult(1, [waste], "waste_mult") == 2
    assert apply_named_mult(100, [shop], "travel_mult") == 100
    assert "boutique" in modifier_label(shop)
    soon = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
    assert announcement_remaining_label(soon) == "encore 20 min"


def test_announcement_requires_effect(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "ann-req.db", catalog)
        try:
            with pytest.raises(PlayerError, match="effet"):
                await store.post_village_announcement(GUILD, "dan", "Coucou.", hours=1)
            with pytest.raises(PlayerError, match="effet"):
                await store.post_village_announcement(
                    GUILD, "dan", "Coucou.", hours=1, modifier={}
                )
        finally:
            await store.close()

    _run(body())


def test_village_talk_persists_until_bucket_refresh(catalog, tmp_path: Path) -> None:
    async def body() -> None:
        store = await open_store(tmp_path / "talk.db", catalog)
        try:
            await store.get_or_create(GUILD, USER)
            await store.record_village_talk(
                GUILD,
                USER,
                "dan",
                "T'as du pain ?",
                "(Hoche la tête.) Oui.",
                bucket=10,
                intent="buy",
                item_key="bread",
                display="stock",
                board_keys=["bread"],
            )
            last = await store.last_village_talk(GUILD, USER, "dan", bucket=10)
            assert last is not None
            assert last.question == "T'as du pain ?"
            assert last.response == "(Hoche la tête.) Oui."
            assert last.intent == "buy"
            assert last.item_key == "bread"
            assert last.display == "stock"
            assert last.board_keys == ["bread"]
            await store.record_village_talk(
                GUILD,
                USER,
                "dan",
                "Et le café ?",
                "Oui.",
                bucket=10,
                intent="none",
                item_key="coffee",
                display="stock",
                board_keys=["coffee"],
            )
            known = await store.village_talk_known_keys(
                GUILD, USER, "dan", bucket=10
            )
            assert known == {"bread", "coffee"}
            assert await store.village_talk_known_keys(
                GUILD, USER, "dan", bucket=11
            ) == set()
            assert await store.last_village_talk(GUILD, USER, "dan", bucket=11) is None
            hist = await store.list_village_talk(GUILD, USER, "dan", bucket=10)
            assert hist == [
                ("T'as du pain ?", "(Hoche la tête.) Oui."),
                ("Et le café ?", "Oui."),
            ]
            assert await store.list_village_talk(GUILD, USER, "dan", bucket=11) == []
            await store.set_village_focus(GUILD, USER, "dan", 10)
            assert await store.village_focus(GUILD, USER) == ("dan", 10)
            await store.clear_village_talk_intent(GUILD, USER, "dan")
            cleared = await store.last_village_talk(GUILD, USER, "dan", bucket=10)
            assert cleared is not None
            assert cleared.intent == "none"
            assert cleared.display == "stock"
            await store.reset_player(GUILD, USER)
            assert await store.last_village_talk(GUILD, USER, "dan", bucket=10) is None
        finally:
            await store.close()

    _run(body())


def test_npc_personalities(catalog) -> None:
    hedwig = catalog.get_npc("hedwig").personality.lower()
    joel = catalog.get_npc("joel").personality.lower()
    gaia = catalog.get_npc("gaia").personality.lower()
    oz = catalog.get_npc("oz").personality.lower()
    esmer = catalog.get_npc("esmer").personality.lower()
    assert "oiseau" in hedwig or "chant" in hedwig
    assert "cochon" in joel
    assert "alien" in gaia
    assert "ne parle" in oz
    assert "vouvoiement" in esmer
    assert catalog.get_npc("esmer").hook
    assert catalog.get_npc("hedwig").hook
    assert catalog.get_npc("joel").hook
    hedwig = catalog.get_npc("hedwig")
    assert hedwig.hook_for("night") != hedwig.hook_for("dawn")


def test_npc_role_labels_are_plain(catalog) -> None:
    assert npc_role_label(catalog.get_npc("esmer")) == "Identification"
    assert npc_role_label(catalog.get_npc("gaia")) == "Note environnementale"
    assert npc_role_label(catalog.get_npc("gabriel")) == "Passeur"
    assert npc_role_label(catalog.get_npc("maurice")) == "Réparations"
    assert npc_role_label(catalog.get_npc("agathe")) == "Rachat"
    assert npc_role_label(catalog.get_npc("dan")) == "Vendeur"
    assert npc_role_label(catalog.get_npc("oz")) == "Fossiles"


def test_npc_card_header_packs_identity_beside_portrait(catalog) -> None:
    import discord

    from cogs.azure.views import _npc_card_header

    enabled = [n for n in catalog.npcs if n.enabled]
    assert len(enabled) >= 8
    for npc in enabled:
        attachments: list = []
        role = npc_role_label(npc)
        ident = f"-# 0 · **{role}** · {npc.description}"
        header = _npc_card_header(
            catalog, npc, ident, env_good=True, attachments=attachments
        )
        assert isinstance(header, discord.ui.Section), npc.key
        text = header.children[0].content
        assert npc.name in text
        assert role in text
        assert npc.description in text
        assert attachments


def test_talk_show_keys(catalog) -> None:
    from common.player.models import GearInstance, PlayerSnapshot, Stack
    from common.village import talk_show_keys

    snap = PlayerSnapshot(
        guild_id=GUILD,
        user_id=USER,
        energy=100,
        energy_max=100,
        energy_max_base=100,
        money=0,
        milieu_key="pond",
        created_at="",
        stacks=[Stack(item_key="broken_bottle", quantity=1)],
        gear=[GearInstance(id=1, item_key="lantern", durability=2)],
    )
    dan = talk_show_keys(catalog, catalog.get_npc("dan"), snap=snap)
    assert "bread" in dan
    assert "lantern" not in dan
    assert talk_show_keys(catalog, catalog.get_npc("gabriel"), snap=snap) == []
    assert "broken_bottle" in talk_show_keys(catalog, catalog.get_npc("agathe"), snap=snap)
    assert "lantern" in talk_show_keys(catalog, catalog.get_npc("maurice"), snap=snap)
    assert "broken_bottle" in talk_show_keys(catalog, catalog.get_npc("gaia"), snap=snap)
    assert talk_show_keys(catalog, catalog.get_npc("oz"), snap=snap) == []
    esmer_keys = talk_show_keys(catalog, catalog.get_npc("esmer"), snap=snap)
    assert "broken_bottle" in esmer_keys
    assert "lantern" in esmer_keys


def test_talk_select_description() -> None:
    assert talk_select_description(length_cm=20.0, weight_kg=0.4) == "20 cm · 0.4 kg"
    assert (
        talk_select_description(
            length_cm=20.0, weight_kg=0.4, price_plain="8 br."
        )
        == "20 cm · 0.4 kg · 8 br."
    )
    assert talk_select_description(qty=3) == "×3"
    assert talk_select_description(qty=3, price_plain="12 br.") == "×3 · 12 br."
    assert talk_select_description(qty=1, price_plain="4 br.") == "4 br."
    assert talk_select_description() == ""


def test_focus_talk_board_never_dumps_catalog(catalog) -> None:
    agathe = catalog.get_npc("agathe")
    display, keys = focus_talk_board(
        agathe, display="none", board_keys=[], shown_key="perch"
    )
    assert display == "purse"
    assert keys == ["perch"]
    display, keys = focus_talk_board(agathe, display="purse", board_keys=[])
    assert keys == []
    gaia = catalog.get_npc("gaia")
    display, keys = focus_talk_board(gaia, display="env", board_keys=[])
    assert keys == []
    dan = catalog.get_npc("dan")
    display, keys = focus_talk_board(
        dan,
        display="stock",
        board_keys=["bread", "worm_bait", "coffee", "lantern", "extra"],
        item_key="bread",
    )
    assert len(keys) <= 4
    esmer = catalog.get_npc("esmer")
    display, keys = focus_talk_board(
        esmer, display="none", board_keys=[], shown_key="compass"
    )
    assert display == "inspect"
    assert keys == ["compass"]


def test_waste_rates(catalog) -> None:
    from common.village import cleanup_waste_items, waste_env_points, waste_sell_unit

    keys = {it.key for it in cleanup_waste_items(catalog)}
    assert "broken_bottle" in keys
    assert "planks" in keys
    bottle = catalog.get_item("broken_bottle")
    assert waste_sell_unit(bottle) == 1
    assert waste_env_points(bottle) == 1
    assert waste_sell_unit(bottle, [{"waste_mult": 2.0}]) == 2


def test_talk_facts_include_prices(catalog) -> None:
    from common.player.models import CaughtSpecimen, PlayerSnapshot, Stack
    from common.village.talk import talk_facts

    dan = catalog.get_npc("dan")
    sold = talk_facts(catalog, dan, env_score=0, skulls=0)
    assert "bread = Pain" in sold
    assert "12" in sold
    assert "bargain=true" in sold
    already = talk_facts(
        catalog, dan, env_score=0, skulls=0, bargain=bargain_modifier(catalog, dan)
    )
    assert "DÉJÀ cédé" in already
    assert "bargain=false" in already
    agathe = catalog.get_npc("agathe")
    snap = PlayerSnapshot(
        guild_id=GUILD,
        user_id=USER,
        energy=100,
        energy_max=100,
        energy_max_base=100,
        money=40,
        milieu_key="pond",
        created_at="",
        stacks=[Stack(item_key="broken_bottle", quantity=2)],
    )
    specs = [
        CaughtSpecimen(
            id=1, species_key="perch", length_cm=20.0, weight_kg=0.4, caught_at=""
        )
    ]
    bought = talk_facts(
        catalog, agathe, env_score=0, skulls=0, snap=snap, specimens=specs
    )
    assert "broken_bottle = Bouteille cassée ×2" in bought
    assert "perch =" in bought
    assert "40" in bought


def test_talk_facts_esmer_wiki_and_dossier(catalog) -> None:
    from common.player.models import PlayerSnapshot, Stack
    from common.village.talk import sanitize_talk, talk_facts

    esmer = catalog.get_npc("esmer")
    snap = PlayerSnapshot(
        guild_id=GUILD,
        user_id=USER,
        energy=80,
        energy_max=100,
        energy_max_base=100,
        money=0,
        milieu_key="pond",
        created_at="",
        stacks=[Stack(item_key="red_gem", quantity=1)],
    )
    wiki = talk_facts(catalog, esmer, env_score=50, skulls=0, snap=snap)
    assert "intent=none" in wiki
    assert "+2 %" in wiki or "+2%" in wiki
    assert "red_gem" in wiki
    assert "Fortune" in wiki
    shown = talk_facts(
        catalog, esmer, env_score=50, skulls=0, snap=snap, shown_key="compass"
    )
    assert "walk_time_mult" in shown or "marche" in shown.lower()
    assert "compass" in shown
    raw = sanitize_talk(
        {
            "reponse": "(Incline légèrement la tête.) Permettez, voyez.",
            "intent": "buy",
            "item_key": "bread",
            "display": "none",
            "board_keys": [],
            "bargain": True,
        },
        catalog,
        esmer,
        shown_key="compass",
    )
    assert raw["intent"] == "none"
    assert raw["bargain"] is False
    assert raw["display"] == "inspect"
    assert "compass" in raw["board_keys"]


def test_talk_intent_block_quantity(catalog) -> None:
    from common.player.models import PlayerSnapshot
    from common.village import talk_intent_block

    dan = catalog.get_npc("dan")
    snap = PlayerSnapshot(
        guild_id=GUILD,
        user_id=USER,
        energy=100,
        energy_max=100,
        energy_max_base=100,
        money=12,
        milieu_key="pond",
        created_at="",
    )
    assert (
        talk_intent_block(
            catalog, dan, snap, [], [],
            intent="buy", item_key="bread", milieu_key=None, quantity=3,
        )
        == "Pas assez d'argent"
    )
    snap.money = 40
    assert (
        talk_intent_block(
            catalog, dan, snap, [], [],
            intent="buy", item_key="bread", milieu_key=None, quantity=3,
        )
        is None
    )
    assert (
        talk_intent_block(
            catalog, catalog.get_npc("gabriel"), snap, [], [],
            intent="travel", item_key=None, milieu_key="pond", quantity=1,
        )
        == "Tu es déjà là"
    )
    from common.player.models import Stack

    snap.money = 400
    snap.stacks = [Stack(item_key="bread", quantity=98)]
    assert (
        talk_intent_block(
            catalog, dan, snap, [], [],
            intent="buy", item_key="bread", milieu_key=None, quantity=3,
        )
        == "Pas de place dans le sac"
    )
    assert (
        talk_intent_block(
            catalog, dan, snap, [], [],
            intent="buy", item_key=None, milieu_key=None,
        )
        == "Dis-lui ce que tu veux lui acheter"
    )
    assert (
        talk_intent_block(
            catalog, catalog.get_npc("agathe"), snap, [], [],
            intent="sell", item_key=None, milieu_key=None,
        )
        == "Dis-lui ce que tu veux lui vendre"
    )
    assert (
        talk_intent_block(
            catalog, catalog.get_npc("maurice"), snap, [], [],
            intent="repair", item_key=None, milieu_key=None,
        )
        == "Dis-lui ce que tu veux faire réparer"
    )
    assert (
        talk_intent_block(
            catalog, catalog.get_npc("gabriel"), snap, [], [],
            intent="travel", item_key=None, milieu_key=None,
        )
        == "Dis-lui où tu veux aller"
    )
