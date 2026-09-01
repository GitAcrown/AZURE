"""Cog AZURE — slash commands joueur + outils owner (LayoutView)."""

from __future__ import annotations

import logging
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from common.asset_emojis import species_emoji, with_emoji
from common.catalog import Catalog, CatalogError
from common.discord_ui import ack, send_error, sync_slash_to_guilds
from common.display import item_display, species_display
from common.emoji_setup import (
    bind_application_emojis,
    bound_count,
    setup_application_emojis,
)
from common.fishing import FishingError, context_from_world, simulate
from common.money import format_money
from common.llm.client import LLMClient, LLMOpenAIError
from common.player import PlayerError, PlayerSnapshot, PlayerStore
from common.village import (
    ANNOUNCE_KINDS,
    build_announcement_modifier,
    env_quality_mult,
    environment_is_good,
    modifier_label,
    pick_announcer,
    present_npcs,
    skull_score,
    village_bucket,
)
from common.village.talk import STREAM_EDIT_INTERVAL_S, talk_npc
from common.world import weather_bucket

from .views import (
    CatalogView,
    EmojisGalleryView,
    NoticeView,
    OnboardingView,
    PubView,
    RecordsView,
    VillageAnnounceView,
    load_monde_view,
    load_player_hub,
    load_village_view,
    start_cast_flow,
    travel_arrival_flash,
)

logger = logging.getLogger("AZURE.Cog")

_METHOD_LABELS = {"rod": "canne", "net": "filet"}


def _equipped_item_key(snap: PlayerSnapshot, slot: str) -> str | None:
    eq = snap.equipped.get(slot)
    if eq is None:
        return None
    if eq.gear is not None:
        return eq.gear.item_key
    return eq.item_key


def _catalog(bot: commands.Bot) -> Catalog:
    catalog = getattr(bot, "catalog", None)
    if catalog is None:
        raise RuntimeError("Catalogue AZURE non chargé.")
    return catalog


def _store(bot: commands.Bot) -> PlayerStore:
    store = getattr(bot, "store", None)
    if store is None:
        raise RuntimeError("Store joueur AZURE non chargé.")
    return store


def _item_choices(
    catalog: Catalog,
    current: str,
    *,
    allowed: Optional[set[str]] = None,
) -> list[app_commands.Choice[str]]:
    q = (current or "").lower()
    out: list[app_commands.Choice[str]] = []
    for it in catalog.items:
        if allowed is not None and it.key not in allowed:
            continue
        if q and q not in it.key.lower() and q not in it.name.lower():
            continue
        out.append(app_commands.Choice(name=f"{it.name} ({it.key})", value=it.key))
        if len(out) >= 25:
            break
    return out


async def _send_view(interaction: discord.Interaction, view: discord.ui.LayoutView) -> None:
    files = getattr(view, "attachments", None) or None
    if interaction.response.is_done():
        kwargs: dict = {"view": view}
        if files:
            kwargs["attachments"] = files
        try:
            await interaction.edit_original_response(**kwargs)
        except discord.HTTPException:
            follow: dict = {"view": view, "ephemeral": True}
            if files:
                follow["files"] = files
            try:
                await interaction.followup.send(**follow)
            except discord.HTTPException:
                return
        return
    kwargs = {"view": view, "ephemeral": True}
    if files:
        kwargs["files"] = files
    try:
        await interaction.response.send_message(**kwargs)
    except discord.HTTPException:
        return


async def _maybe_onboard(
    interaction: discord.Interaction, store: PlayerStore, catalog: Catalog
) -> bool:
    """True si le diaporama a été envoyé : l'appelant doit s'arrêter."""
    guild = interaction.guild
    if guild is None:
        return False
    snap = await store.get_or_create(guild.id, interaction.user.id)
    if snap.onboarding_done:
        return False
    await _send_view(interaction, OnboardingView(catalog, page=0))
    return True


class OwnerGroup(app_commands.Group):
    """Groupe `/admin …` réservé au propriétaire."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await interaction.client.is_owner(interaction.user):
            raise app_commands.CheckFailure("owner")
        return True


class Azure(commands.Cog):
    admin = OwnerGroup(
        name="admin",
        description="Outils développeur AZURE",
        guild_only=True,
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._synced_dev = False
        self._talk_gen: dict[tuple[int, int], int] = {}

    async def cog_load(self) -> None:
        if not self._expire_announcements.is_running():
            self._expire_announcements.start()

    async def cog_unload(self) -> None:
        if self._expire_announcements.is_running():
            self._expire_announcements.cancel()

    @tasks.loop(minutes=5)
    async def _expire_announcements(self) -> None:
        store = getattr(self.bot, "store", None)
        if store is None:
            return
        try:
            await store.expire_village_announcements()
        except Exception:
            logger.exception("Expiration des annonces village")

    @_expire_announcements.before_loop
    async def _expire_announcements_ready(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await bind_application_emojis(self.bot, _catalog(self.bot))
        if self._synced_dev:
            return
        targets: list[discord.abc.Snowflake] = list(self.bot.guilds)
        raw = getattr(self.bot, "config", {}).get("DEV_GUILD")
        if not targets and raw:
            try:
                targets = [discord.Object(id=int(raw))]
            except (TypeError, ValueError):
                targets = []
        if not targets:
            logger.warning("Aucun serveur à synchroniser (slash). az!sync ~ sur le serveur voulu.")
            return
        try:
            names, ok, failed = await sync_slash_to_guilds(self.bot, targets)
            logger.info(
                "Slash commands sync (serveur, pas global) : %s — %d/%d serveur(s)%s",
                ", ".join(names) or "—",
                ok,
                len(targets),
                f" · {failed} échec(s)" if failed else "",
            )
            self._synced_dev = True
        except discord.HTTPException as exc:
            logger.warning("Sync slash impossible : %s", exc)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            names, ok, failed = await sync_slash_to_guilds(self.bot, [guild])
            logger.info(
                "Slash commands sync sur %s (%s) : %s%s",
                guild.name,
                guild.id,
                ", ".join(names) or "—",
                " · échec" if failed or not ok else "",
            )
        except discord.HTTPException as exc:
            logger.warning("Sync slash impossible sur %s : %s", guild.id, exc)

    @app_commands.command(name="profil", description="Profil, sac et dex.")
    @app_commands.guild_only()
    async def profil(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await send_error(interaction, "Cette commande s'utilise sur un serveur.")
            return
        store = _store(self.bot)
        cat = _catalog(self.bot)
        if await _maybe_onboard(interaction, store, cat):
            return
        view = await load_player_hub(
            cat, store, guild.id, interaction.user.id, interaction.user.display_name
        )
        await _send_view(interaction, view)

    @app_commands.command(name="monde", description="Carte : météo, pêche, et y aller à pied.")
    @app_commands.guild_only()
    async def monde(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await send_error(interaction, "Cette commande s'utilise sur un serveur.")
            return
        store = _store(self.bot)
        cat = _catalog(self.bot)
        if await _maybe_onboard(interaction, store, cat):
            return
        snap = await store.get_or_create(guild.id, interaction.user.id)
        flash = travel_arrival_flash(cat, snap)
        await _send_view(
            interaction,
            await load_monde_view(
                cat, store, guild.id, interaction.user.id, flash=flash
            ),
        )

    @app_commands.command(name="pecher", description="Lance dans le milieu actuel.")
    @app_commands.guild_only()
    async def pecher(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await send_error(interaction, "Cette commande s'utilise sur un serveur.")
            return
        store = _store(self.bot)
        cat = _catalog(self.bot)
        if await _maybe_onboard(interaction, store, cat):
            return
        if not await ack(interaction, ephemeral=True):
            return
        await start_cast_flow(interaction, cat, store)

    @app_commands.command(name="records", description="Meilleures prises du serveur.")
    @app_commands.guild_only()
    async def records(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await send_error(interaction, "Cette commande s'utilise sur un serveur.")
            return
        store = _store(self.bot)
        cat = _catalog(self.bot)
        if await _maybe_onboard(interaction, store, cat):
            return
        rows = await store.list_guild_records(guild.id)
        names: dict[int, str] = {}
        for _key, user_id, _length, _weight in rows:
            if user_id in names:
                continue
            member = guild.get_member(user_id)
            names[user_id] = member.display_name if member is not None else f"<@{user_id}>"
        await _send_view(interaction, RecordsView(cat, rows, names=names))

    @app_commands.command(name="village", description="Place du village : étals, atelier, passages.")
    @app_commands.guild_only()
    async def village(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await send_error(interaction, "Cette commande s'utilise sur un serveur.")
            return
        store = _store(self.bot)
        cat = _catalog(self.bot)
        if await _maybe_onboard(interaction, store, cat):
            return
        if not await ack(interaction, ephemeral=True):
            return
        snap = await store.get_or_create(guild.id, interaction.user.id)
        flash = travel_arrival_flash(cat, snap)
        view = await load_village_view(
            cat, store, guild.id, interaction.user.id, flash=flash, restore_focus=True
        )
        await _send_view(interaction, view)

    async def handle_village_talk(
        self,
        interaction: discord.Interaction,
        *,
        npc_key: str,
        question: str,
        shown_key: str | None = None,
        shown_extra: str | None = None,
        shown_catch_id: int | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await send_error(interaction, "Cette commande s'utilise sur un serveur.")
            return
        client = getattr(self.bot, "llm", None)
        if client is None or not isinstance(client, LLMClient):
            await send_error(interaction, "Le dialogue n'est pas disponible.")
            return
        store = _store(self.bot)
        cat = _catalog(self.bot)
        if not await ack(interaction, ephemeral=False):
            return
        talk_key = (guild.id, interaction.user.id)
        token = self._talk_gen.get(talk_key, 0) + 1
        self._talk_gen[talk_key] = token
        snap = await store.snapshot(guild.id, interaction.user.id)
        specimens = await store.list_caught(guild.id, interaction.user.id)
        present = present_npcs(cat, guild.id, skulls=skull_score(cat, snap))
        npc = next((n for n in present if n.key == npc_key), None)
        if npc is None:
            await send_error(interaction, "Cette personne n'est plus là.")
            return
        env_score = await store.environment_score(guild.id)
        announcements = await store.list_village_announcements(guild.id)
        bucket = village_bucket(cat)
        history = await store.list_village_talk(
            guild.id, interaction.user.id, npc_key, bucket=bucket
        )
        shown_label = ""
        if shown_key:
            try:
                cat.get_item(shown_key)
                shown_label = item_display(cat, shown_key)
            except Exception:
                try:
                    cat.get_species(shown_key)
                    shown_label = species_display(cat, shown_key)
                except Exception:
                    shown_label = shown_key
            if shown_extra:
                shown_label = f"{shown_label} · {shown_extra}"
            question = f"{shown_label} · {question}" if question else shown_label

        async def _show(
            *,
            status: str,
            response: str = "",
            intent: str = "none",
            item_key: str | None = None,
            milieu_key: str | None = None,
            display: str = "none",
            board_keys: list[str] | None = None,
            quantity: int = 1,
            flash: str = "",
        ) -> None:
            if self._talk_gen.get(talk_key) != token:
                return
            view = await load_village_view(
                cat,
                store,
                guild.id,
                interaction.user.id,
                npc_key=npc_key,
                talk_question=question,
                talk_response=response,
                talk_status=status,
                talk_intent=intent,
                talk_item_key=item_key,
                talk_milieu_key=milieu_key,
                talk_display=display,
                talk_board_keys=board_keys,
                talk_quantity=quantity,
                talk_catch_id=shown_catch_id,
                flash=flash,
            )
            await _send_view(interaction, view)

        await _show(status="pending")
        last_edit = 0.0

        async def _on_partial(partial: str) -> None:
            nonlocal last_edit
            if self._talk_gen.get(talk_key) != token:
                return
            now = time.monotonic()
            if now - last_edit < STREAM_EDIT_INTERVAL_S:
                return
            last_edit = now
            await _show(status="streaming", response=partial)

        bargain = await store.get_village_bargain(
            guild.id, interaction.user.id, npc_key, bucket=bucket
        )
        try:
            result = await talk_npc(
                client,
                cat,
                npc,
                question,
                history=history,
                env_score=env_score,
                skulls=skull_score(cat, snap),
                snap=snap,
                specimens=specimens,
                announcements=announcements,
                bargain=bargain,
                shown_key=shown_key,
                shown_extra=shown_extra,
                on_partial=_on_partial,
            )
        except LLMOpenAIError:
            logger.exception("Dialogue village")
            if self._talk_gen.get(talk_key) == token:
                await send_error(interaction, "Cette personne n'a pas entendu.")
            return
        if self._talk_gen.get(talk_key) != token:
            return
        granted = False
        if result.get("bargain"):
            granted = await store.set_village_bargain(
                guild.id, interaction.user.id, npc, bucket=bucket
            )
        await store.record_village_talk(
            guild.id,
            interaction.user.id,
            npc_key,
            question,
            result["reponse"],
            bucket=bucket,
            intent=str(result.get("intent") or "none"),
            item_key=result.get("item_key"),
            milieu_key=result.get("milieu_key"),
            display=str(result.get("display") or "none"),
            board_keys=list(result.get("board_keys") or []),
            quantity=int(result.get("quantity") or 1),
        )
        flash = f"**{npc.name or npc.key} cède un peu.**" if granted else ""
        await _show(
            status="done",
            response=result["reponse"],
            intent=result["intent"],
            item_key=result["item_key"],
            milieu_key=result["milieu_key"],
            display=str(result.get("display") or "none"),
            board_keys=list(result.get("board_keys") or []),
            quantity=int(result.get("quantity") or 1),
            flash=flash,
        )

    @admin.command(name="catalog", description="Résumé du catalogue YAML.")
    async def admin_catalog(self, interaction: discord.Interaction) -> None:
        cat = _catalog(self.bot)
        bound, total = bound_count(cat)
        await interaction.response.send_message(
            view=CatalogView(cat, bound, total),
            ephemeral=True,
        )

    @admin.command(name="emojis", description="Upload tous les assets (espèces, items, UI) en emojis d'application.")
    async def admin_emojis(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        cat = _catalog(self.bot)

        async def progress(done: int, total: int, name: str) -> None:
            if done == 0 or done == total or done % 20 == 0:
                await interaction.edit_original_response(
                    view=NoticeView("Emojis", f"{done}/{total}", note=name)
                )

        report = await setup_application_emojis(self.bot, cat, progress=progress)
        body = report.summary()
        err_note = ""
        if report.errors:
            sample = "\n".join(f"• {e}" for e in report.errors[:8])
            extra = f"\n+{len(report.errors) - 8} autres" if len(report.errors) > 8 else ""
            err_note = f"**Erreurs**\n{sample}{extra}"
        title = "Emojis" if not report.errors else "Emojis · incomplet"
        await interaction.edit_original_response(
            view=EmojisGalleryView.from_catalog(cat, title=title, summary=body, errors=err_note)
        )

    @admin.command(name="give", description="Donne un item du catalogue.")
    @app_commands.describe(
        item="Clé d'item (ex. bread, coastal_rod)",
        quantite="Quantité",
        joueur="Cible — toi par défaut",
    )
    async def admin_give(
        self,
        interaction: discord.Interaction,
        item: str,
        quantite: app_commands.Range[int, 1, 99] = 1,
        joueur: Optional[discord.Member] = None,
    ) -> None:
        guild = interaction.guild
        assert guild is not None
        target = joueur or interaction.user
        store = _store(self.bot)
        cat = _catalog(self.bot)
        try:
            added = await store.add_item(guild.id, target.id, item, int(quantite))
        except PlayerError as exc:
            await send_error(interaction, str(exc))
            return
        await interaction.response.send_message(
            view=NoticeView(
                "Give",
                f"{item_display(cat, item, extra=f' ×{added}')} → {target.mention}",
            ),
            ephemeral=True,
        )

    @admin_give.autocomplete("item")
    async def give_item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return _item_choices(_catalog(self.bot), current)

    @admin.command(name="money", description="Ajoute ou retire de l'argent en bronze (100 = 1 argent).")
    @app_commands.describe(delta="Bronze (négatif pour retirer)", joueur="Cible — toi par défaut")
    async def admin_money(
        self,
        interaction: discord.Interaction,
        delta: int,
        joueur: Optional[discord.Member] = None,
    ) -> None:
        guild = interaction.guild
        assert guild is not None
        target = joueur or interaction.user
        store = _store(self.bot)
        cat = _catalog(self.bot)
        new_value = await store.add_money(guild.id, target.id, delta)
        await interaction.response.send_message(
            view=NoticeView(
                "Argent",
                f"{target.mention} → {format_money(new_value, cat.game.money)}",
                note=f"Δ {delta:+d} br.",
            ),
            ephemeral=True,
        )

    @admin.command(name="energy", description="Fixe l'énergie (bornée 0–max).")
    @app_commands.describe(valeur="Nouvelle énergie", joueur="Cible — toi par défaut")
    async def admin_energy(
        self,
        interaction: discord.Interaction,
        valeur: int,
        joueur: Optional[discord.Member] = None,
    ) -> None:
        guild = interaction.guild
        assert guild is not None
        target = joueur or interaction.user
        store = _store(self.bot)
        new_value = await store.set_energy(guild.id, target.id, valeur)
        snap = await store.snapshot(guild.id, target.id)
        await interaction.response.send_message(
            view=NoticeView(
                "Énergie",
                f"{target.mention} → {new_value}/{snap.energy_max} énergie",
            ),
            ephemeral=True,
        )

    @admin.command(name="reset", description="Efface le profil AZURE.")
    @app_commands.describe(joueur="Cible — toi par défaut")
    async def admin_reset(
        self,
        interaction: discord.Interaction,
        joueur: Optional[discord.Member] = None,
    ) -> None:
        guild = interaction.guild
        assert guild is not None
        if not await ack(interaction, ephemeral=True):
            return
        target = joueur or interaction.user
        store = _store(self.bot)
        await store.reset_player(guild.id, target.id)
        await _send_view(
            interaction,
            NoticeView("Reset", f"Profil effacé pour {target.mention}.", note="Ce serveur uniquement."),
        )

    @admin.command(name="bonus", description="Publie un bonus temporaire. L'effet est obligatoire.")
    @app_commands.describe(
        bonus="Effet appliqué aux prix, passages ou réparations",
        texte="Réplique dans le salon (pas l'effet)",
        heures="Durée du bonus, en heures",
    )
    @app_commands.choices(
        bonus=[
            app_commands.Choice(name=label[:100], value=kind)
            for kind, label in ANNOUNCE_KINDS.items()
        ]
    )
    async def admin_bonus(
        self,
        interaction: discord.Interaction,
        bonus: str,
        texte: str,
        heures: app_commands.Range[int, 1, 72] = 6,
    ) -> None:
        guild = interaction.guild
        assert guild is not None
        cat = _catalog(self.bot)
        store = _store(self.bot)
        bucket = weather_bucket(None, cat.game.world)
        roster = present_npcs(cat, guild.id, skulls=0, bucket=bucket)
        if not roster:
            await send_error(interaction, "Personne n'est là pour l'instant.")
            return
        speaker = pick_announcer(roster, guild.id, bucket)
        modifier = build_announcement_modifier(bonus)
        if not modifier:
            await send_error(interaction, "cet effet n'existe pas.")
            return
        modifier["hours"] = int(heures)
        env_score = await store.environment_score(guild.id)
        env_good = environment_is_good(cat, env_score)
        posted = await store.post_village_announcement(
            guild.id,
            speaker.key,
            texte,
            hours=int(heures),
            modifier=modifier,
        )
        note = f"**{modifier_label(modifier)}** · {heures} h"
        view = VillageAnnounceView(cat, speaker, texte, env_good=env_good, note=note)
        raw = getattr(self.bot, "config", {}).get("VILLAGE_CHANNEL")
        channel = None
        if raw:
            try:
                channel = self.bot.get_channel(int(raw)) or await self.bot.fetch_channel(int(raw))
            except (TypeError, ValueError, discord.HTTPException):
                channel = None
        if channel is not None and hasattr(channel, "send"):
            files = getattr(view, "attachments", None) or None
            kwargs: dict = {"view": view}
            if files:
                kwargs["files"] = files
            try:
                await channel.send(**kwargs)
            except discord.HTTPException:
                logger.warning("Impossible de poster le bonus village (salon).")
        await interaction.response.send_message(
            view=NoticeView(
                "Bonus",
                f"{speaker.name or speaker.key} · jusqu'à {posted.ends_at}",
                note=note,
            ),
            ephemeral=True,
        )

    @admin.command(name="pub", description="Poste la présentation du jeu dans un salon.")
    @app_commands.describe(salon="Salon où poster (celui-ci par défaut)")
    async def admin_pub(
        self,
        interaction: discord.Interaction,
        salon: Optional[discord.TextChannel] = None,
    ) -> None:
        guild = interaction.guild
        assert guild is not None
        channel = salon or interaction.channel
        if channel is None or not hasattr(channel, "send"):
            await send_error(interaction, "Impossible de poster ici.")
            return
        if not await ack(interaction, ephemeral=True):
            return
        view = PubView(_catalog(self.bot))
        files = getattr(view, "attachments", None) or None
        kwargs: dict = {"view": view}
        if files:
            kwargs["files"] = files
        try:
            await channel.send(**kwargs)
        except discord.HTTPException:
            await send_error(interaction, "Le salon n'accepte pas le message.")
            return
        mention = getattr(channel, "mention", None) or str(channel)
        await interaction.followup.send(
            view=NoticeView("Pub", f"Présentation postée dans {mention}."),
            ephemeral=True,
        )

    @admin.command(name="monde", description="État du monde + debug (bucket, prochaine rotation).")
    async def admin_monde(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None
        cat = _catalog(self.bot)
        store = _store(self.bot)
        await store.get_or_create(guild.id, interaction.user.id)
        await _send_view(
            interaction,
            await load_monde_view(
                cat, store, guild.id, interaction.user.id, debug=True
            ),
        )

    @admin.command(name="simuler", description="Simule N lancers (équilibrage).")
    @app_commands.describe(
        n="Nombre de lancers",
        milieu="ocean, river ou pond — milieu actuel par défaut",
        methode="rod ou net — outil équipé par défaut",
    )
    async def admin_simuler(
        self,
        interaction: discord.Interaction,
        n: app_commands.Range[int, 1, 10000] = 1000,
        milieu: Optional[str] = None,
        methode: Optional[str] = None,
    ) -> None:
        guild = interaction.guild
        assert guild is not None
        cat = _catalog(self.bot)
        snap = await _store(self.bot).get_or_create(guild.id, interaction.user.id)
        milieu_key = (milieu or snap.milieu_key or "").strip()
        if not milieu_key:
            await send_error(interaction, "Précise un milieu, ou va quelque part avec /monde.")
            return
        try:
            milieu_obj = cat.get_milieu(milieu_key)
        except CatalogError:
            await send_error(interaction, f"milieu inconnu : {milieu_key!r}")
            return
        method = (methode or "").strip()
        if not method:
            tool_key = _equipped_item_key(snap, "tool")
            if tool_key:
                tool = cat.get_item(tool_key)
                method = (tool.equipment.capture_method if tool.equipment else None) or ""
        if method not in {"rod", "net"}:
            await send_error(interaction, "Méthode invalide : `rod` ou `net`.")
            return
        bait = None
        bait_key = _equipped_item_key(snap, "bait")
        if bait_key:
            bait = cat.get_item(bait_key)
        hook = None
        hook_key = _equipped_item_key(snap, "hook")
        if hook_key:
            hook = cat.get_item(hook_key)
        env_score = await store.environment_score(guild.id)
        ctx = context_from_world(
            cat,
            guild.id,
            milieu_obj.key,
            method,
            bait=bait,
            hook=hook,
            env_quality_mult=env_quality_mult(cat, env_score),
        )
        try:
            counts = simulate(cat, ctx, int(n))
        except FishingError as exc:
            await send_error(interaction, str(exc))
            return
        total = sum(counts.values()) or 1
        lines: list[str] = []
        for i, (key, count) in enumerate(counts.most_common(15), start=1):
            spec = cat.get_species(key)
            pct = 100.0 * count / total
            label = with_emoji(species_emoji(key), spec.name)
            lines.append(f"**{i}.** {label} · `{pct:.1f}%`")
        method_label = _METHOD_LABELS.get(method, method)
        note = f"{n} lancers · {milieu_obj.name} · {method_label}"
        await interaction.response.send_message(
            view=NoticeView("Simulation", "\n".join(lines) or "—", note=note),
            ephemeral=True,
        )

    @admin_simuler.autocomplete("milieu")
    async def admin_simuler_milieu(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        cat = _catalog(self.bot)
        q = (current or "").lower()
        out: list[app_commands.Choice[str]] = []
        for m in cat.milieus:
            if q and q not in m.key.lower() and q not in m.name.lower():
                continue
            out.append(app_commands.Choice(name=m.name, value=m.key))
        return out

    @admin_simuler.autocomplete("methode")
    async def admin_simuler_methode(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        q = (current or "").lower()
        out: list[app_commands.Choice[str]] = []
        for key, label in _METHOD_LABELS.items():
            if q and q not in key and q not in label:
                continue
            out.append(app_commands.Choice(name=label, value=key))
        return out


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Azure(bot))
