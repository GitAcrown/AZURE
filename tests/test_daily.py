"""Quête du jour : avis Place, compteur perso, paiement unique."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from common.catalog import load_catalog
from common.daily import (
    DailyStatus,
    daily_day_key,
    daily_milieu_key,
    daily_place_block,
    daily_talk_line,
)
from common.fishing import Specimen
from common.player import open_store
from common.player.models import PlayerSnapshot
from common.village.talk import talk_facts

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
PARIS = ZoneInfo("Europe/Paris")
GUILD = 100
USER = 42


def _run(coro):
    return asyncio.run(coro)


def test_same_guild_same_day_same_milieu() -> None:
    catalog = load_catalog(ASSETS)
    now = datetime(2026, 8, 31, 15, 0, tzinfo=PARIS)
    a = daily_milieu_key(catalog, GUILD, now=now)
    b = daily_milieu_key(catalog, GUILD, now=now)
    assert a == b
    assert a in {m.key for m in catalog.milieus}


def test_day_key_flips_at_paris_midnight() -> None:
    catalog = load_catalog(ASSETS)
    before = datetime(2026, 8, 31, 23, 59, tzinfo=PARIS)
    after = datetime(2026, 9, 1, 0, 1, tzinfo=PARIS)
    assert daily_day_key(catalog, before) == "2026-08-31"
    assert daily_day_key(catalog, after) == "2026-09-01"


def test_place_block_progress_and_done() -> None:
    catalog = load_catalog(ASSETS)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=PARIS)
    key = daily_milieu_key(catalog, GUILD, now=now)
    open_ = DailyStatus(
        day_key="2026-08-31",
        milieu_key=key,
        count=2,
        target=3,
        rewarded=False,
        reward_bronze=40,
    )
    text = daily_place_block(catalog, open_)
    assert text.startswith("**Quête du jour**")
    assert "**toi 2/3**" in text
    assert "**village 0/9**" in text
    assert "faite" not in text
    assert "- " not in text
    done = DailyStatus(
        day_key="2026-08-31",
        milieu_key=key,
        count=3,
        target=3,
        rewarded=True,
        reward_bronze=40,
        guild_count=9,
        guild_target=9,
        guild_done=True,
    )
    closed = daily_place_block(catalog, done)
    assert "**toi faite**" in closed
    assert "**village faite**" in closed


def test_three_keeps_pay_once(tmp_path: Path) -> None:
    catalog = load_catalog(ASSETS)

    async def body() -> None:
        store = await open_store(tmp_path / "d.db", catalog)
        try:
            await store.get_or_create(GUILD, USER)
            want = daily_milieu_key(catalog, GUILD)
            other = next(k for k in ("ocean", "river", "pond") if k != want)
            await store.set_milieu(GUILD, USER, want)
            fish = next(
                s.key
                for s in catalog.species
                if s.environment == want and s.capture.method == "rod"
            )
            spec = Specimen(20.0, 0.4)
            first = await store.finish_cast(GUILD, USER, fish, specimen=spec)
            assert first.daily_count == 1
            assert first.daily_just_rewarded == 0
            assert first.daily_guild_count == 1
            second = await store.finish_cast(GUILD, USER, fish, specimen=spec)
            assert second.daily_count == 2
            third = await store.finish_cast(GUILD, USER, fish, specimen=spec)
            assert third.daily_just_rewarded == 40
            assert third.daily_count == 3
            assert third.daily_guild_count == 3
            assert third.daily_guild_just_completed is False
            snap = await store.snapshot(GUILD, USER)
            assert snap.money == 40
            fourth = await store.finish_cast(GUILD, USER, fish, specimen=spec)
            assert fourth.daily_note is False
            snap = await store.snapshot(GUILD, USER)
            assert snap.money == 40

            missed = await store.tick_daily(GUILD, USER, kept=True, milieu_key=other)
            assert missed[0].count == 3
            released = await store.tick_daily(GUILD, USER, kept=False, milieu_key=want)
            assert released[0].count == 3
        finally:
            await store.close()

    _run(body())


def test_wrong_milieu_and_release_do_not_count(tmp_path: Path) -> None:
    catalog = load_catalog(ASSETS)

    async def body() -> None:
        store = await open_store(tmp_path / "w.db", catalog)
        try:
            await store.get_or_create(GUILD, USER)
            want = daily_milieu_key(catalog, GUILD)
            other = next(k for k in ("ocean", "river", "pond") if k != want)
            status, pay, flash = await store.tick_daily(
                GUILD, USER, kept=True, milieu_key=other
            )
            assert status.count == 0
            assert pay == 0
            assert flash is False
            status, pay, flash = await store.tick_daily(
                GUILD, USER, kept=False, milieu_key=want
            )
            assert status.count == 0
            assert flash is False
            status, pay, flash = await store.tick_daily(
                GUILD, USER, kept=True, milieu_key=want
            )
            assert status.count == 1
            assert flash is True
            assert pay == 0
        finally:
            await store.close()

    _run(body())


def test_new_day_resets_progress(tmp_path: Path) -> None:
    catalog = load_catalog(ASSETS)
    day1 = datetime(2026, 8, 31, 10, 0, tzinfo=PARIS)
    day2 = datetime(2026, 9, 1, 10, 0, tzinfo=PARIS)

    async def body() -> None:
        store = await open_store(tmp_path / "n.db", catalog)
        try:
            await store.get_or_create(GUILD, USER)
            want = daily_milieu_key(catalog, GUILD, now=day1)
            await store.tick_daily(
                GUILD, USER, kept=True, milieu_key=want, now=day1
            )
            await store.tick_daily(
                GUILD, USER, kept=True, milieu_key=want, now=day1
            )
            mid = await store.daily_status(GUILD, USER, now=day1)
            assert mid.count == 2
            nxt = await store.daily_status(GUILD, USER, now=day2)
            assert nxt.count == 0
            assert nxt.rewarded is False
        finally:
            await store.close()

    _run(body())


def test_gaia_and_esmer_know_the_board() -> None:
    catalog = load_catalog(ASSETS)
    snap = PlayerSnapshot(
        guild_id=GUILD,
        user_id=USER,
        energy=100,
        energy_max=100,
        energy_max_base=100,
        money=0,
        milieu_key="pond",
        created_at="",
    )
    line = daily_talk_line(catalog, GUILD)
    gaia = talk_facts(catalog, catalog.get_npc("gaia"), env_score=50, skulls=0, snap=snap)
    esmer = talk_facts(catalog, catalog.get_npc("esmer"), env_score=50, skulls=0, snap=snap)
    assert line in gaia
    assert line in esmer
    assert "Place" in line
    assert "village" in line


def test_village_quest_caps_per_player_and_rewards_env_once(tmp_path: Path) -> None:
    catalog = load_catalog(ASSETS)
    a, b, c = 11, 12, 13

    async def body() -> None:
        store = await open_store(tmp_path / "guild-daily.db", catalog)
        try:
            want = daily_milieu_key(catalog, GUILD)
            for uid in (a, b, c):
                await store.get_or_create(GUILD, uid)
            start = await store.environment_score(GUILD)
            for uid in (a, b):
                for _ in range(3):
                    status, _pay, _flash = await store.tick_daily(
                        GUILD, uid, kept=True, milieu_key=want
                    )
                assert status.guild_just_completed is False
            mid = await store.daily_status(GUILD, a)
            assert mid.guild_count == 6
            assert mid.guild_done is False
            extra = await store.tick_daily(GUILD, a, kept=True, milieu_key=want)
            assert extra[0].count == 3
            assert extra[0].guild_count == 6
            for _ in range(2):
                await store.tick_daily(GUILD, c, kept=True, milieu_key=want)
            last, _pay, flash = await store.tick_daily(
                GUILD, c, kept=True, milieu_key=want
            )
            assert last.guild_count == 9
            assert last.guild_done is True
            assert last.guild_just_completed is True
            assert flash is True
            assert await store.environment_score(GUILD) == start + 2
            await store.get_or_create(GUILD, 14)
            again, _pay, _flash = await store.tick_daily(
                GUILD, 14, kept=True, milieu_key=want
            )
            assert again.guild_count == 10
            assert again.guild_just_completed is False
            assert await store.environment_score(GUILD) == start + 2
            text = daily_place_block(catalog, last)
            assert "**village faite**" in text
        finally:
            await store.close()

    _run(body())
