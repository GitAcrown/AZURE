"""UI Components v2 AZURE — LayoutViews profil / notices / inspection."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import discord

from common.asset_emojis import (
    asset_file,
    gallery_sections,
    item_emoji,
    item_is_collectible,
    npc_emoji,
    paginate_gallery,
    species_emoji,
    ui_emoji,
    with_emoji,
)
from common.catalog import Catalog, Item
from common.catalog.models import Npc
from common.discord_ui import (
    append_controls,
    edit_error,
    make_container,
    prepend_tabs,
    section_with_thumbnail,
)
from common.display import (
    dialogue_turn,
    italic_text,
    item_display,
    species_display,
    npc_speech_text,
    title_name,
    weather_display,
    weather_of,
)
from common.money import format_money, format_money_plain
from common.player import (
    CaughtSpecimen,
    CastResult,
    DexRow,
    PendingCast,
    PlayerError,
    PlayerSnapshot,
    PlayerStore,
)
from common.player.db import BAIT_SLOT, GEAR_SLOTS
from common.fishing import cast_energy_parts
from common.player.store import carry_compartment, collect_owned_effects
from common.village import (
    ROLE_LABELS,
    SHOP_TAB_LABELS,
    VillageAnnouncement,
    announcement_remaining_label,
    environment_is_good,
    environment_is_great,
    environment_is_poor,
    environment_pct,
    fossil_replicas,
    npc_portrait_filename,
    npc_role_label,
    apply_named_mult,
    cleanup_waste_items,
    modifier_label,
    passeur_price,
    present_npcs,
    price_modifiers,
    shop_stock,
    talk_intent_block,
    talk_show_keys,
    waste_env_points,
    waste_sell_unit,
    skull_score,
    specimen_price,
    travel_minutes_left,
    travel_remaining_s,
    village_bucket,
    walk_minutes,
)
from common.world import (
    milieu_at_phrase,
    next_bucket_at,
    season_label,
    time_label,
    weather_at,
    world_state,
)

SLOT_LABELS = {
    "tool": "Outil",
    "hook": "Crochet",
    "bait": "Appât",
    "objet": "Objet",
}

DISPLAY_SLOTS = ("tool", "hook", "bait", "objet")

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
}

DEX_GROUP_LABELS = {
    "fishdex": "Poisson",
    "creaturedex": "Créature",
    "shelldex": "Coquillage",
}

DEX_PAGE_SIZE = 12
SAC_PAGE_SIZE = 12

RARITY_LABELS = {
    "common": "commune",
    "uncommon": "peu commune",
    "rare": "rare",
}


def _energy_bar(current: int, maximum: int, width: int = 10) -> str:
    if maximum <= 0:
        return "░" * width
    filled = max(0, min(width, round(width * current / maximum)))
    return "█" * filled + "░" * (width - filled)


def _durability_label(item: Item, remaining: int | None) -> str:
    if remaining is None or item.durability is None:
        return ""
    dur = item.durability
    if dur.max_days is not None or dur.unit == "days":
        return f" · `{remaining} j`"
    if dur.max is not None:
        return f" · `{remaining}/{dur.max}`"
    return ""


def _equipped_key(eq) -> str | None:
    if eq is None:
        return None
    if eq.gear is not None:
        return eq.gear.item_key
    return eq.item_key


def _select_emoji(item_key: str | None) -> discord.PartialEmoji | None:
    if not item_key:
        return None
    return _partial_emoji(item_emoji(item_key))


def _partial_emoji(code: str | None) -> discord.PartialEmoji | None:
    code = (code or "").strip()
    if not (code.startswith("<") and code.endswith(">")):
        return None
    try:
        return discord.PartialEmoji.from_str(code)
    except Exception:
        return None


def _is_collectible_key(catalog: Catalog, item_key: str) -> bool:
    try:
        return item_is_collectible(catalog.get_item(item_key))
    except Exception:
        return False


def _inventory_parts(
    catalog: Catalog, snap: PlayerSnapshot, *, collectibles: bool = False
) -> list[str]:
    equipped_ids = {eq.gear_id for eq in snap.equipped.values() if eq.gear_id is not None}
    parts: list[str] = []
    for stack in snap.stacks:
        if _is_collectible_key(catalog, stack.item_key) != collectibles:
            continue
        parts.append(item_display(catalog, stack.item_key, extra=f" ×{stack.quantity}"))
    for gear in snap.gear:
        if gear.id in equipped_ids:
            continue
        if _is_collectible_key(catalog, gear.item_key) != collectibles:
            continue
        extra = ""
        try:
            item = catalog.get_item(gear.item_key)
            extra = _durability_label(item, gear.durability)
        except Exception:
            pass
        parts.append(item_display(catalog, gear.item_key, extra=extra))
    return parts


def _collectible_group(catalog: Catalog, group: str) -> list[Item]:
    return [
        it
        for it in catalog.items
        if it.enabled
        and it.collection is not None
        and it.collection.collectible
        and it.collection.group == group
    ]


def _shadow_collection_lines(
    catalog: Catalog, snap: PlayerSnapshot, items: list[Item], label: str
) -> list[str]:
    if not items:
        return []
    owned = snap.owned_keys()
    unlocked = 0
    bits: list[str] = []
    for it in items:
        has = it.key in owned
        if has:
            unlocked += 1
        code = (item_emoji(it.key, shadow=not has) or "").strip()
        if not code:
            code = (item_emoji(it.key, shadow=has) or "").strip()
        bits.append(code or ("✦" if has else "·"))
    return [f"**{label}** · {unlocked}/{len(items)}", " ".join(bits)]


def _gem_items(catalog: Catalog) -> list[Item]:
    return _collectible_group(catalog, "gemstones")


def _collection_block(catalog: Catalog, snap: PlayerSnapshot) -> str:
    lines = [f"**Dex** · {snap.dex_found}/{snap.dex_total}"]
    lines.extend(_shadow_collection_lines(catalog, snap, _gem_items(catalog), "Gemmes"))
    lines.extend(
        _shadow_collection_lines(
            catalog, snap, _collectible_group(catalog, "fossil_replicas"), "Fossiles"
        )
    )
    return "\n".join(lines)


def _equipped_lines(catalog: Catalog, snap: PlayerSnapshot) -> list[str]:
    lines: list[str] = []
    for slot in DISPLAY_SLOTS:
        label = SLOT_LABELS[slot]
        eq = snap.equipped.get(slot)
        key = _equipped_key(eq)
        if not key:
            lines.append(f"**{label}** · —")
            continue
        extra = ""
        try:
            item = catalog.get_item(key)
            extra = _durability_label(item, eq.gear.durability if eq and eq.gear else None)
        except Exception:
            pass
        lines.append(f"**{label}** · {item_display(catalog, key, extra=extra)}")
    return lines


def travel_arrival_flash(catalog: Catalog, snap: PlayerSnapshot) -> str:
    if not snap.just_arrived:
        return ""
    try:
        milieu = catalog.get_milieu(snap.just_arrived)
        phrase = milieu_at_phrase(milieu.key, milieu.name)
    except Exception:
        phrase = snap.just_arrived
    return f"**Tu es arrivé à {phrase}.**"


def _onboarding_lines(snap: PlayerSnapshot) -> str:
    if snap.milieu_key:
        return (
            "**Cannes** et **filet** déjà dans le sac.\n"
            "**/pecher** pour lancer · **/village** pour vendre · **/profil** pour équiper."
        )
    return (
        "**Premier pas**\n"
        "1. Choisis un milieu avec **/monde** (premier aller **immédiat**)\n"
        "2. **/pecher** pour lancer — **Relancer** après une prise\n"
        "3. **/village** pour vendre · **/profil** pour l'**objet** actif"
    )


def _milieu_profile_line(catalog: Catalog, snap: PlayerSnapshot) -> str:
    if not snap.milieu_key:
        return "—"
    try:
        name = catalog.get_milieu(snap.milieu_key).name
    except Exception:
        name = snap.milieu_key
    state = world_state(catalog.game.world, snap.guild_id, [snap.milieu_key])
    weather = state.weathers[snap.milieu_key]
    line = f"{name} · {weather_display(weather)} · {time_label(state.time_of_day)}"
    remaining = travel_remaining_s(snap.travel_arrives_at)
    if snap.travel_dest and remaining is not None and remaining > 0:
        try:
            dest_name = catalog.get_milieu(snap.travel_dest).name
        except Exception:
            dest_name = snap.travel_dest
        mins = travel_minutes_left(remaining)
        line += f" · **en route** vers {dest_name} (**{mins} min**)"
    return line


class ProfilView(discord.ui.LayoutView):
    def __init__(
        self,
        catalog: Catalog,
        snap: PlayerSnapshot,
        display_name: str,
        *,
        flash: str = "",
    ) -> None:
        super().__init__(timeout=180)
        self.catalog = catalog
        self.display_name = display_name

        milieu = _milieu_profile_line(catalog, snap)
        equipped_lines = _equipped_lines(catalog, snap)

        subtitle = f"-# {display_name}"
        if snap.created:
            subtitle += " · nouveau pêcheur"

        bar = _energy_bar(snap.energy, snap.energy_max)
        energy_line = f"**Énergie** · `{bar}` {snap.energy}/{snap.energy_max}"
        if snap.coffee_minutes:
            pct = int(round(snap.coffee_pct * 100))
            energy_line += f"\n-# Café · +{pct}% encore {snap.coffee_minutes} min"
        children: list = [
            discord.ui.TextDisplay("## Profil"),
            discord.ui.TextDisplay(subtitle),
            discord.ui.Separator(),
            discord.ui.TextDisplay(
                f"{energy_line}\n"
                f"**Argent** · {format_money(snap.money, catalog.game.money, compact=False)}\n"
                f"**Milieu** · {milieu}"
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay("### Équipé\n" + "\n".join(equipped_lines)),
            discord.ui.Separator(),
            discord.ui.TextDisplay("### Collection\n" + _collection_block(catalog, snap)),
        ]
        if snap.created or not snap.milieu_key:
            children += [
                discord.ui.Separator(),
                discord.ui.TextDisplay(_onboarding_lines(snap)),
            ]
        arrived = travel_arrival_flash(catalog, snap)
        if arrived:
            children += [discord.ui.Separator(), discord.ui.TextDisplay(arrived)]
        options = _equip_options(catalog, snap)
        note = flash or (
            "Rien d'autre à équiper."
            if not options
            else "Un seul **objet** actif. Change canne, crochet, appât ou objet."
        )
        append_controls(
            children,
            note=note,
            select_row=discord.ui.ActionRow(_EquipSelect(options)) if options else None,
        )
        self.add_item(make_container(*children))


def _equip_options(catalog: Catalog, snap: PlayerSnapshot) -> list[discord.SelectOption]:
    options: list[discord.SelectOption] = []
    for slot in DISPLAY_SLOTS:
        eq = snap.equipped.get(slot)
        if eq is None:
            continue
        item_name = ""
        key = _equipped_key(eq)
        if key:
            try:
                item_name = catalog.get_item(key).name
            except Exception:
                item_name = key
        label = f"RETIRER · {SLOT_LABELS[slot]}"
        if item_name:
            label = f"{label} · {item_name}"
        kwargs: dict = {
            "label": label[:100],
            "value": f"unequip:{slot}",
        }
        emoji = _select_emoji(_equipped_key(eq))
        if emoji is not None:
            kwargs["emoji"] = emoji
        options.append(discord.SelectOption(**kwargs))
    equipped_ids = {eq.gear_id for eq in snap.equipped.values() if eq.gear_id is not None}
    current_bait = snap.equipped.get("bait")
    current_bait_key = current_bait.item_key if current_bait else None
    for gear in snap.gear:
        if gear.id in equipped_ids:
            continue
        try:
            item = catalog.get_item(gear.item_key)
        except Exception:
            continue
        eq = item.equipment
        if eq is None or not eq.equippable or eq.slot not in GEAR_SLOTS:
            continue
        slot_label = SLOT_LABELS.get(eq.slot or "", eq.slot or "?")
        extra = _durability_label(item, gear.durability)
        kwargs = {
            "label": f"{slot_label} · {item.name}{extra}".strip()[:100],
            "value": f"gear:{gear.id}",
        }
        emoji = _select_emoji(item.key)
        if emoji is not None:
            kwargs["emoji"] = emoji
        options.append(discord.SelectOption(**kwargs))
    for stack in snap.stacks:
        if stack.item_key == current_bait_key:
            continue
        try:
            item = catalog.get_item(stack.item_key)
        except Exception:
            continue
        eq = item.equipment
        if eq is None or not eq.equippable or eq.slot != BAIT_SLOT:
            continue
        kwargs = {
            "label": f"Appât · {item.name} ×{stack.quantity}"[:100],
            "value": f"bait:{item.key}",
        }
        emoji = _select_emoji(item.key)
        if emoji is not None:
            kwargs["emoji"] = emoji
        options.append(discord.SelectOption(**kwargs))
    return options[:25]


class _EquipSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(
            placeholder="Équiper ou retirer…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await edit_error(interaction, "Cette commande s'utilise sur un serveur.")
            return
        store = getattr(interaction.client, "store", None)
        catalog = getattr(interaction.client, "catalog", None)
        if store is None or catalog is None:
            await edit_error(interaction, "AZURE n'est pas prêt.")
            return
        assert isinstance(store, PlayerStore)
        assert isinstance(catalog, Catalog)
        raw = self.values[0]
        try:
            if raw.startswith("unequip:"):
                slot = raw.split(":", 1)[1]
                await store.unequip(guild.id, interaction.user.id, slot)
                flash = f"**{SLOT_LABELS.get(slot, slot)}** retiré."
            elif raw.startswith("gear:"):
                gear_id = int(raw.split(":", 1)[1])
                slot = await store.equip_gear(guild.id, interaction.user.id, gear_id)
                snap = await store.snapshot(guild.id, interaction.user.id)
                key = _equipped_key(snap.equipped.get(slot))
                name = item_display(catalog, key or "", emoji=True) if key else "—"
                flash = f"**{SLOT_LABELS.get(slot, slot)}** → {name}"
            elif raw.startswith("bait:"):
                item_key = raw.split(":", 1)[1]
                await store.equip_bait(guild.id, interaction.user.id, item_key)
                flash = f"**Appât** → {item_display(catalog, item_key)}"
            else:
                raise PlayerError("choix invalide")
        except (PlayerError, ValueError) as exc:
            snap = await store.snapshot(guild.id, interaction.user.id)
            await interaction.response.edit_message(
                view=ProfilView(
                    catalog,
                    snap,
                    interaction.user.display_name,
                    flash=f"**{str(exc).rstrip('.')}.**",
                )
            )
            return
        snap = await store.snapshot(guild.id, interaction.user.id)
        await interaction.response.edit_message(
            view=ProfilView(
                catalog, snap, interaction.user.display_name, flash=flash
            )
        )


class MondeView(discord.ui.LayoutView):
    """Saison / météo, et select pour se déplacer à pied."""

    def __init__(
        self,
        catalog: Catalog,
        snap: PlayerSnapshot,
        *,
        debug: bool = False,
        flash: str = "",
    ) -> None:
        super().__init__(timeout=180)
        current_key = snap.milieu_key
        dest = snap.travel_dest
        remaining = travel_remaining_s(snap.travel_arrives_at)
        walking = bool(dest and remaining is not None and remaining > 0)
        keys = [m.key for m in catalog.milieus]
        state = world_state(catalog.game.world, snap.guild_id, keys)
        clock = state.at.strftime("%H:%M")
        lines = [
            f"**Saison** · {season_label(state.season)}",
            f"**Moment** · {time_label(state.time_of_day)} · `{clock}`",
        ]
        walk_mins = travel_minutes_left(remaining) if walking and remaining is not None else 0
        effects = collect_owned_effects(catalog, snap.gear, snap.stacks, snap.equipped)
        forecast = bool(effects.get("destination_weather_forecast_minutes"))
        milieu_lines: list[str] = []
        for milieu in catalog.milieus:
            weather = state.weathers[milieu.key]
            bit = f"**{milieu.name}** · {weather_display(weather)}"
            if current_key == milieu.key:
                bit += " · **ici**"
            if walking and dest == milieu.key:
                bit += f" · **en route** · encore **{walk_mins} min**"
            if forecast:
                nxt_weather = weather_at(
                    snap.guild_id, milieu.key, state.next_bucket_at, catalog.game.world
                )
                bit += f" · puis {weather_display(nxt_weather)}"
            milieu_lines.append(bit)
        minutes = walk_minutes(catalog, snap)
        children: list = [
            discord.ui.TextDisplay("## Monde"),
            discord.ui.TextDisplay(
                f"-# {catalog.game.world.timezone} · **marche gratuite** · {minutes} min"
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay("\n".join(lines)),
            discord.ui.Separator(),
            discord.ui.TextDisplay("\n".join(milieu_lines)),
        ]
        options: list[discord.SelectOption] = []
        selected = dest if walking else None
        for m in catalog.milieus:
            if current_key == m.key:
                continue
            opt_kwargs: dict = {
                "label": m.name,
                "value": m.key,
                "default": selected is not None and m.key == selected,
            }
            if walking and dest == m.key:
                opt_kwargs["description"] = f"en route · encore {walk_mins} min"[:100]
            elif m.description:
                opt_kwargs["description"] = m.description[:100]
            options.append(discord.SelectOption(**opt_kwargs))
        note = flash or travel_arrival_flash(catalog, snap)
        if not note and not current_key:
            note = "Premier milieu : **immédiat**. Ensuite, **marche gratuite**."
        if not note and walking and dest:
            try:
                dest_name = catalog.get_milieu(dest).name
            except Exception:
                dest_name = dest
            note = f"**En route** vers {dest_name} · encore **{walk_mins} min**"
        if debug:
            nxt = state.next_bucket_at.strftime("%H:%M")
            debug_note = f"bucket `{state.bucket}` · prochaine rotation `{nxt}`"
            note = f"{note} · {debug_note}" if note else debug_note
        append_controls(
            children,
            note=note,
            select_row=discord.ui.ActionRow(_MilieuSelect(options, debug=debug)) if options else None,
        )
        self.add_item(make_container(*children))


class _MilieuSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption], *, debug: bool = False) -> None:
        super().__init__(
            placeholder="Marcher vers un milieu…",
            min_values=1,
            max_values=1,
            options=options,
        )
        self._debug = debug

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await edit_error(interaction, "Cette commande s'utilise sur un serveur.")
            return
        store = getattr(interaction.client, "store", None)
        catalog = getattr(interaction.client, "catalog", None)
        if store is None or catalog is None:
            await edit_error(interaction, "AZURE n'est pas prêt.")
            return
        assert isinstance(store, PlayerStore)
        assert isinstance(catalog, Catalog)
        key = self.values[0]
        try:
            changed, new_key = await store.set_milieu(guild.id, interaction.user.id, key)
        except PlayerError as exc:
            snap = await store.snapshot(guild.id, interaction.user.id)
            await interaction.response.edit_message(
                view=MondeView(catalog, snap, debug=self._debug, flash=f"**{str(exc).rstrip('.')}.**")
            )
            return
        snap = await store.snapshot(guild.id, interaction.user.id)
        milieu = catalog.get_milieu(new_key)
        phrase = milieu_at_phrase(milieu.key, milieu.name)
        remaining = travel_remaining_s(snap.travel_arrives_at)
        walking = bool(snap.travel_dest == new_key and remaining is not None and remaining > 0)
        if walking:
            mins = travel_minutes_left(remaining or 0)
            if changed:
                flash = f"**Tu marches** vers {phrase} · encore **{mins} min**."
            else:
                flash = f"**Tu es déjà en route** vers {phrase}."
        elif not changed:
            flash = f"**Tu restes à {phrase}.**"
        else:
            flash = f"**Tu es à {phrase}.** Ensuite : **/pecher**."
        await interaction.response.edit_message(
            view=MondeView(catalog, snap, debug=self._debug, flash=flash)
        )


async def _apply_view(interaction: discord.Interaction, view: discord.ui.LayoutView) -> None:
    kwargs: dict = {"view": view}
    files = getattr(view, "attachments", None)
    if files:
        kwargs["attachments"] = files
    if interaction.response.is_done():
        await interaction.edit_original_response(**kwargs)
    else:
        await interaction.response.edit_message(**kwargs)


async def prepare_catch_view(
    catalog: Catalog,
    store: PlayerStore,
    pending: PendingCast,
) -> CatchView:
    existing = pending.catch_view
    if isinstance(existing, CatchView):
        return existing
    preview = pending.preview
    if preview is None:
        preview = await store.preview_cast(
            pending.guild_id,
            pending.user_id,
            pending.species_key,
            bait_consumed=pending.bait_consumed,
            energy=pending.energy,
            energy_max=pending.energy_max,
        )
        pending.preview = preview
    view = CatchView(catalog, preview)
    pending.catch_view = view
    return view


async def run_bite_timer(
    interaction: discord.Interaction,
    catalog: Catalog,
    pending: PendingCast,
) -> None:
    try:
        await asyncio.sleep(pending.wait_s)
        if pending.resolved:
            return
        await interaction.edit_original_response(view=BiteView(catalog, pending, phase="open"))
        await asyncio.sleep(pending.window_s)
        if pending.resolved:
            return
        pending.resolved = True
        await interaction.edit_original_response(
            view=NoticeView("Fuite", "Il s'est enfui.")
        )
    except (discord.HTTPException, discord.NotFound):
        pending.resolved = True


def _slot_item_line(catalog: Catalog, slot: str, item_key: str | None) -> str:
    label = SLOT_LABELS[slot]
    if not item_key:
        return f"**{label}** · —"
    return f"**{label}** · {item_display(catalog, item_key)}"


class BiteView(discord.ui.LayoutView):
    """Mini-jeu : pas de thumbnail, espèce non nommée."""

    def __init__(self, catalog: Catalog, pending: PendingCast, *, phase: str = "waiting") -> None:
        extra = pending.wait_s + pending.window_s + 15
        super().__init__(timeout=max(45, extra))
        self.catalog = catalog
        self.pending = pending
        self.phase = phase
        if pending.method == "net":
            title = "Quelque chose dans le filet…"
        else:
            title = "Ça mord…"
        label = pending.action_label
        if phase == "open":
            style = discord.ButtonStyle.success
            disabled = False
        else:
            style = discord.ButtonStyle.secondary
            disabled = not pending.trap_early
        try:
            milieu_name = catalog.get_milieu(pending.milieu_key).name
        except Exception:
            milieu_name = pending.milieu_key or "—"
        weather_bit = weather_display(weather_of(catalog, pending.weather_key))
        gear = "\n".join(
            _slot_item_line(catalog, slot, key)
            for slot, key in (
                ("tool", pending.tool_key),
                ("hook", pending.hook_key),
                ("bait", pending.bait_key),
            )
        )
        children: list = [
            discord.ui.TextDisplay(f"## {title}"),
            discord.ui.TextDisplay(f"-# {milieu_name} · {weather_bit}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(gear),
        ]
        bite_note = "Attends le **bon moment**." if phase != "open" else "**C'est le moment !**"
        append_controls(
            children,
            note=bite_note,
            button_row=discord.ui.ActionRow(
                _BiteButton(label=label, style=style, disabled=disabled, phase=phase)
            ),
        )
        self.add_item(make_container(*children))


class _BiteButton(discord.ui.Button):
    def __init__(
        self,
        *,
        label: str,
        style: discord.ButtonStyle,
        disabled: bool,
        phase: str,
    ) -> None:
        super().__init__(style=style, label=label, disabled=disabled)
        self.phase = phase

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, BiteView):
            return
        pending = parent.pending
        catalog = parent.catalog
        if pending.resolved:
            await interaction.response.edit_message(view=NoticeView("Fuite", "Trop tard."))
            return
        if self.phase == "waiting" and pending.trap_early:
            pending.resolved = True
            await interaction.response.edit_message(view=NoticeView("Fuite", "Trop tôt."))
            return
        if self.phase != "open":
            await interaction.response.defer()
            return
        pending.resolved = True
        if not interaction.response.is_done():
            await interaction.response.defer()
        store = getattr(interaction.client, "store", None)
        if store is None or not isinstance(store, PlayerStore):
            await edit_error(interaction, "AZURE n'est pas prêt.")
            return
        view = pending.catch_view if isinstance(pending.catch_view, CatchView) else None
        prep = pending.prep_task
        if view is None and isinstance(prep, asyncio.Task):
            try:
                view = await prep
            except (PlayerError, asyncio.CancelledError):
                view = None
        if view is None:
            try:
                view = await prepare_catch_view(catalog, store, pending)
            except PlayerError as exc:
                await edit_error(interaction, str(exc))
                return
        try:
            result = await store.finish_cast(
                pending.guild_id,
                pending.user_id,
                pending.species_key,
                bait_consumed=pending.bait_consumed,
                energy=pending.energy,
                energy_max=pending.energy_max,
                preview=pending.preview,
            )
            await _apply_view(interaction, CatchView(catalog, result))
        except PlayerError as exc:
            await edit_error(interaction, str(exc))
            return


class CatchView(discord.ui.LayoutView):
    """Résultat d'un lancer : thumbnail sprite, pas d'emoji du même asset."""

    def __init__(self, catalog: Catalog, result: CastResult) -> None:
        super().__init__(timeout=120)
        self.attachments: list[discord.File] = []
        species = catalog.get_species(result.species_key)

        name_body = discord.ui.TextDisplay(title_name(species.name))
        header: discord.ui.Item = name_body
        path = catalog.assets_root / "species" / species.assets.sprite
        file = asset_file(path, preload=True)
        if file is not None:
            self.attachments.append(file)
            header = section_with_thumbnail(name_body, file)
        else:
            header = discord.ui.TextDisplay(
                with_emoji(species_emoji(species.key), f"**{species.name}**")
            )

        group = DEX_GROUP_LABELS.get(species.collection.group or "", species.collection.group or "—")
        rarity = RARITY_LABELS.get(species.rarity, species.rarity)
        sub = discord.ui.TextDisplay(f"-# {group} · {rarity}")

        captures = f"**Captures** · {result.catch_count}"
        if result.is_new:
            captures += " · **nouvelle**"
        if result.length_cm is not None:
            captures += f"\n**Taille** · `{result.length_cm} cm`"
        if result.weight_kg is not None:
            captures += f"\n**Poids** · `{result.weight_kg} kg`"
        medals: list[str] = []
        if result.personal_record:
            medals.append(with_emoji(ui_emoji("MEDAL1"), "**record perso**"))
        guild_medals = {
            1: ("MEDAL4", "**or**"),
            2: ("MEDAL3", "**argent**"),
            3: ("MEDAL2", "**bronze**"),
        }
        guild_medal = guild_medals.get(result.guild_rank or 0)
        if guild_medal is not None:
            medals.append(with_emoji(ui_emoji(guild_medal[0]), guild_medal[1]))
        if medals:
            captures += "\n" + " · ".join(medals)

        children: list = [header, sub]
        desc = italic_text(species.description)
        if desc:
            children += [discord.ui.Separator(), discord.ui.TextDisplay(desc)]
        children += [discord.ui.Separator(), discord.ui.TextDisplay(captures)]

        note = f"**énergie** `{result.energy}/{result.energy_max}`"
        if result.bait_consumed:
            note += f" · **appât** −1 {item_display(catalog, result.bait_consumed)}"
        if result.waste_key:
            note += f" · **déchet** {item_display(catalog, result.waste_key)}"
        if result.loot_key:
            note += f" · **trouvé** {item_display(catalog, result.loot_key)}"
        if result.hook_broke:
            note += " · **crochet usé**"
        if result.kept:
            note += f" · **dans le sac** · {result.carry_used}/{result.carry_max}"
        else:
            note += f" · **relâché** · **sac plein** {result.carry_used}/{result.carry_max}"
        self.result = result
        self.catalog = catalog
        shareable = bool(result.is_new or result.personal_record or result.guild_rank or result.loot_key)
        recast_ok, energy_bit = _recast_energy_note(catalog, result)
        if energy_bit:
            note += f" · {energy_bit}"
        buttons = [_RecastButton(disabled=not recast_ok)]
        if shareable:
            buttons.append(_ShareCatchButton())
        append_controls(children, note=note, button_row=discord.ui.ActionRow(*buttons))
        self.add_item(make_container(*children))


def _recast_energy_note(catalog: Catalog, result: CastResult) -> tuple[bool, str]:
    snap = result.snap
    base = int(catalog.game.fishing.cast_energy_cost)
    extra = 0
    weather_bit = ""
    if snap is not None and snap.milieu_key:
        effects = collect_owned_effects(
            catalog, snap.gear, snap.stacks, snap.equipped
        )
        weather = weather_at(
            snap.guild_id,
            snap.milieu_key,
            datetime.now(timezone.utc),
            catalog.game.world,
        )
        _base, extra = cast_energy_parts(
            catalog,
            weather.key,
            ignore=bool(effects.get("ignore_bad_weather_fatigue_penalty")),
        )
        base = _base
        if extra:
            weather_bit = f"{weather_display(weather)} **+{extra}** · "
    needed = base + extra
    if result.energy >= needed:
        return True, ""
    return False, f"**pas assez d'énergie** · {weather_bit}il faut **{needed}**"


async def start_cast_flow(
    interaction: discord.Interaction,
    catalog: Catalog,
    store: PlayerStore,
) -> None:
    guild = interaction.guild
    if guild is None:
        await edit_error(interaction, "Cette commande s'utilise sur un serveur.")
        return
    try:
        pending = await store.begin_cast(guild.id, interaction.user.id)
    except PlayerError as exc:
        msg = str(exc)
        snap = await store.get_or_create(guild.id, interaction.user.id)
        if "milieu" in msg.lower():
            await _apply_view(
                interaction,
                MondeView(
                    catalog,
                    snap,
                    flash="**Choisis un milieu** pour pêcher. Premier aller : **immédiat**.",
                ),
            )
            return
        if "outil" in msg.lower() or "équipe" in msg.lower():
            await _apply_view(
                interaction,
                ProfilView(
                    catalog,
                    snap,
                    interaction.user.display_name,
                    flash="**Équipe un outil** pour pêcher.",
                ),
            )
            return
        await _apply_view(
            interaction,
            NoticeView("Pêche", f"**{msg.rstrip('.')}.**"),
        )
        return
    await _apply_view(interaction, BiteView(catalog, pending, phase="waiting"))
    pending.prep_task = asyncio.create_task(prepare_catch_view(catalog, store, pending))
    asyncio.create_task(run_bite_timer(interaction, catalog, pending))


class _RecastButton(discord.ui.Button):
    def __init__(self, *, disabled: bool = False) -> None:
        super().__init__(style=discord.ButtonStyle.primary, label="Relancer", disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, CatchView):
            return
        store = getattr(interaction.client, "store", None)
        if store is None or not isinstance(store, PlayerStore):
            await edit_error(interaction, "AZURE n'est pas prêt.")
            return
        if not interaction.response.is_done():
            await interaction.response.defer()
        await start_cast_flow(interaction, parent.catalog, store)


class _ShareCatchButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(style=discord.ButtonStyle.secondary, label="Partager")

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, CatchView):
            return
        channel = interaction.channel
        if channel is None or not hasattr(channel, "send"):
            await edit_error(interaction, "Impossible de partager ici.")
            return
        result = parent.result
        catalog = parent.catalog
        species = catalog.get_species(result.species_key)
        bits = [f"**{interaction.user.display_name}** a pris {species.name}"]
        if result.length_cm is not None:
            bits.append(f"`{result.length_cm} cm`")
        if result.weight_kg is not None:
            bits.append(f"`{result.weight_kg} kg`")
        if result.personal_record:
            bits.append("**record perso**")
        if result.guild_rank == 1:
            bits.append("**record du serveur**")
        if result.loot_key:
            bits.append(f"et {catalog.get_item(result.loot_key).name}")
        text = " · ".join(bits)
        try:
            await channel.send(text)
        except discord.HTTPException:
            await edit_error(interaction, "Le salon n'accepte pas le message.")
            return
        if interaction.response.is_done():
            await interaction.followup.send("Partagé.", ephemeral=True)
        else:
            await interaction.response.send_message("Partagé.", ephemeral=True)


def _dex_species(catalog: Catalog, group: str) -> list:
    species = [s for s in catalog.species if s.collection.collectible]
    if group != "all":
        species = [s for s in species if s.collection.group == group]
    return species


class DexView(discord.ui.LayoutView):
    """Dex paginé : sprite si découvert, silhouette sinon. Pas de thumbnail PNG."""

    def __init__(
        self,
        catalog: Catalog,
        rows: dict[str, DexRow],
        *,
        group: str = "all",
        page: int = 0,
        found: int = 0,
        total: int = 0,
    ) -> None:
        super().__init__(timeout=180)
        self.catalog = catalog
        self.rows = rows
        self.group = group
        self.found = found
        self.total = total
        species = _dex_species(catalog, group)
        pages = max(1, (len(species) + DEX_PAGE_SIZE - 1) // DEX_PAGE_SIZE) if species else 1
        self.page = max(0, min(page, pages - 1))
        start = self.page * DEX_PAGE_SIZE
        chunk = species[start : start + DEX_PAGE_SIZE]

        lines: list[str] = []
        last_group = None
        for spec in chunk:
            gkey = spec.collection.group or ""
            if gkey != last_group:
                lines.append(f"**{DEX_GROUP_LABELS.get(gkey, gkey or '—')}**")
                last_group = gkey
            row = rows.get(spec.key)
            if row is None:
                lines.append(with_emoji(species_emoji(spec.key, shadow=True), "???"))
                continue
            extra = f" ×{row.catch_count}"
            if row.best_length_cm is not None:
                extra += f" · `{row.best_length_cm} cm`"
            lines.append(species_display(catalog, spec.key, extra=extra))

        group_label = "Tout" if group == "all" else DEX_GROUP_LABELS.get(group, group)
        options = [
            discord.SelectOption(label="Tout", value="all", default=group == "all"),
            discord.SelectOption(label="Poissons", value="fishdex", default=group == "fishdex"),
            discord.SelectOption(label="Créatures", value="creaturedex", default=group == "creaturedex"),
            discord.SelectOption(label="Coquillages", value="shelldex", default=group == "shelldex"),
        ]
        children: list = [
            discord.ui.TextDisplay("## Dex"),
            discord.ui.TextDisplay(
                f"-# {found}/{total} · {group_label}"
                + (f" · page {self.page + 1}/{pages}" if pages > 1 else "")
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay("\n".join(lines) if lines else "Aucune espèce dans ce groupe."),
        ]
        prepend_tabs(children, discord.ui.ActionRow(_DexGroupSelect(options)))
        nav = None
        if pages > 1:
            nav = discord.ui.ActionRow(
                _DexNavButton(delta=-1, disabled=self.page <= 0, label="◀"),
                _DexNavButton(delta=1, disabled=self.page >= pages - 1, label="▶"),
            )
        append_controls(children, button_row=nav)
        self.add_item(make_container(*children))


class _DexNavButton(discord.ui.Button):
    def __init__(self, *, delta: int, disabled: bool, label: str) -> None:
        super().__init__(style=discord.ButtonStyle.secondary, label=label, disabled=disabled)
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, DexView):
            return
        nxt = DexView(
            parent.catalog,
            parent.rows,
            group=parent.group,
            page=parent.page + self.delta,
            found=parent.found,
            total=parent.total,
        )
        await interaction.response.edit_message(view=nxt)


class _DexGroupSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Groupe…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, DexView):
            return
        nxt = DexView(
            parent.catalog,
            parent.rows,
            group=self.values[0],
            page=0,
            found=parent.found,
            total=parent.total,
        )
        await interaction.response.edit_message(view=nxt)


class RecordsView(discord.ui.LayoutView):
    """Meilleures prises du serveur, une par espèce."""

    def __init__(
        self,
        catalog: Catalog,
        rows: list[tuple[str, int, float, float]],
        *,
        names: dict[int, str] | None = None,
    ) -> None:
        super().__init__(timeout=120)
        names = names or {}
        lines: list[str] = []
        for species_key, user_id, length, weight in rows:
            who = names.get(user_id) or f"<@{user_id}>"
            lines.append(
                species_display(
                    catalog,
                    species_key,
                    extra=f" · `{length} cm` · `{weight} kg` · {who}",
                )
            )
        body = "\n".join(lines) if lines else "Aucun record pour l'instant."
        children: list = [
            discord.ui.TextDisplay("## Records"),
            discord.ui.TextDisplay("-# Meilleure prise du serveur par espèce"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(body),
        ]
        self.add_item(make_container(*children))


SAC_TAB_LABELS = {
    "fish": "Poissons",
    "creature": "Créatures",
    "items": "Items",
    "collectibles": "Collection",
}


def _specimens_for_tab(
    catalog: Catalog, specimens: list[CaughtSpecimen], tab: str
) -> list[CaughtSpecimen]:
    if tab == "fish":
        return [s for s in specimens if carry_compartment(catalog, s.species_key) == "fish"]
    if tab == "creature":
        return [s for s in specimens if carry_compartment(catalog, s.species_key) == "creature"]
    return []


def _specimen_line(catalog: Catalog, specimen: CaughtSpecimen) -> str:
    extra = f" · `{specimen.length_cm} cm` · `{specimen.weight_kg} kg`"
    return species_display(catalog, specimen.species_key, extra=extra)


def _drop_specimen_local(
    catalog: Catalog,
    snap: PlayerSnapshot,
    specimens: list[CaughtSpecimen],
    specimen_id: int,
) -> tuple[CaughtSpecimen, list[CaughtSpecimen]]:
    released: CaughtSpecimen | None = None
    remaining: list[CaughtSpecimen] = []
    for spec in specimens:
        if spec.id == specimen_id:
            released = spec
        else:
            remaining.append(spec)
    if released is None:
        raise PlayerError("prise introuvable")
    if carry_compartment(catalog, released.species_key) == "fish":
        snap.fish_carry = max(0, snap.fish_carry - 1)
    else:
        snap.creature_carry = max(0, snap.creature_carry - 1)
    return released, remaining


class SacView(discord.ui.LayoutView):
    """Sac : poissons, créatures, items. Relâcher une prise via le select."""

    def __init__(
        self,
        catalog: Catalog,
        snap: PlayerSnapshot,
        specimens: list[CaughtSpecimen],
        *,
        tab: str = "fish",
        page: int = 0,
        flash: str = "",
    ) -> None:
        super().__init__(timeout=180)
        self.catalog = catalog
        self.snap = snap
        self.specimens = specimens
        self.tab = tab if tab in SAC_TAB_LABELS else "fish"
        self.page = page

        tab_options = [
            discord.SelectOption(
                label=label, value=key, default=self.tab == key
            )
            for key, label in SAC_TAB_LABELS.items()
        ]
        tab_row = discord.ui.ActionRow(_SacTabSelect(tab_options))
        release_row = None
        nav = None
        note = flash

        if self.tab in {"items", "collectibles"}:
            collectibles = self.tab == "collectibles"
            parts = _inventory_parts(catalog, snap, collectibles=collectibles)
            pages = max(1, (len(parts) + SAC_PAGE_SIZE - 1) // SAC_PAGE_SIZE) if parts else 1
            self.page = max(0, min(page, pages - 1))
            start = self.page * SAC_PAGE_SIZE
            chunk = parts[start : start + SAC_PAGE_SIZE]
            if collectibles:
                empty = "Aucune collection dans le sac."
                fallback_note = "Collection du sac — lecture seule."
            else:
                empty = "Aucun item dans le sac."
                fallback_note = "Items du sac — lecture seule."
            body = "\n".join(chunk) if chunk else empty
            subtitle = f"-# {SAC_TAB_LABELS[self.tab]}"
            if pages > 1:
                subtitle += f" · page {self.page + 1}/{pages}"
            note = flash or fallback_note
        else:
            rows = _specimens_for_tab(catalog, specimens, self.tab)
            if self.tab == "fish":
                used, cap = snap.fish_carry, snap.fish_carry_max
                empty = "Aucun poisson dans le sac."
            else:
                used, cap = snap.creature_carry, snap.creature_carry_max
                empty = "Aucune créature dans le sac."
            pages = max(1, (len(rows) + SAC_PAGE_SIZE - 1) // SAC_PAGE_SIZE) if rows else 1
            self.page = max(0, min(page, pages - 1))
            start = self.page * SAC_PAGE_SIZE
            chunk = rows[start : start + SAC_PAGE_SIZE]
            body = "\n".join(_specimen_line(catalog, spec) for spec in chunk) if chunk else empty
            subtitle = f"-# {used}/{cap} · {SAC_TAB_LABELS[self.tab]}"
            if pages > 1:
                subtitle += f" · page {self.page + 1}/{pages}"
            release_options: list[discord.SelectOption] = []
            for spec in chunk:
                try:
                    name = catalog.get_species(spec.species_key).name
                except Exception:
                    name = spec.species_key
                kwargs: dict = {
                    "label": name[:100],
                    "value": str(spec.id),
                    "description": f"{spec.length_cm} cm · {spec.weight_kg} kg"[:100],
                }
                emoji = _partial_emoji(species_emoji(spec.species_key))
                if emoji is not None:
                    kwargs["emoji"] = emoji
                release_options.append(discord.SelectOption(**kwargs))
            note = flash or (
                "Choisis une prise pour la relâcher." if release_options else empty
            )
            if release_options:
                release_row = discord.ui.ActionRow(_SacReleaseSelect(release_options))

        if pages > 1:
            nav = discord.ui.ActionRow(
                _SacNavButton(delta=-1, disabled=self.page <= 0, label="◀"),
                _SacNavButton(delta=1, disabled=self.page >= pages - 1, label="▶"),
            )
        children: list = [
            discord.ui.TextDisplay("## Sac"),
            discord.ui.TextDisplay(subtitle),
            discord.ui.Separator(),
            discord.ui.TextDisplay(body),
        ]
        prepend_tabs(children, tab_row)
        append_controls(children, note=note, button_row=nav, select_row=release_row)
        self.add_item(make_container(*children))


class _SacNavButton(discord.ui.Button):
    def __init__(self, *, delta: int, disabled: bool, label: str) -> None:
        super().__init__(style=discord.ButtonStyle.secondary, label=label, disabled=disabled)
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, SacView):
            return
        nxt = SacView(
            parent.catalog,
            parent.snap,
            parent.specimens,
            tab=parent.tab,
            page=parent.page + self.delta,
        )
        await _apply_view(interaction, nxt)


class _SacTabSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Onglet…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, SacView):
            return
        nxt = SacView(
            parent.catalog,
            parent.snap,
            parent.specimens,
            tab=self.values[0],
            page=0,
        )
        await _apply_view(interaction, nxt)


class _SacReleaseSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(
            placeholder="Relâcher une prise…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, SacView):
            return
        guild = interaction.guild
        if guild is None:
            await edit_error(interaction, "Cette commande s'utilise sur un serveur.")
            return
        store = getattr(interaction.client, "store", None)
        if store is None or not isinstance(store, PlayerStore):
            await edit_error(interaction, "AZURE n'est pas prêt.")
            return
        catalog = parent.catalog
        if not interaction.response.is_done():
            await interaction.response.defer()
        try:
            specimen_id = int(self.values[0])
            released, remaining = _drop_specimen_local(
                catalog, parent.snap, parent.specimens, specimen_id
            )
        except (PlayerError, ValueError) as exc:
            await edit_error(interaction, str(exc))
            return
        flash = f"**Relâché** · {species_display(catalog, released.species_key)}"
        nxt = SacView(
            catalog,
            parent.snap,
            remaining,
            tab=parent.tab,
            page=parent.page,
            flash=flash,
        )
        try:
            persist = asyncio.create_task(
                store.release_caught(guild.id, interaction.user.id, specimen_id)
            )
            await _apply_view(interaction, nxt)
            await persist
        except PlayerError as exc:
            await edit_error(interaction, str(exc))
            return


def _npc_face_emoji(npc: Npc, *, env_good: bool) -> discord.PartialEmoji | None:
    use_alt = bool((npc.portraits.good or npc.portraits.bad) and not env_good)
    return _partial_emoji(npc_emoji(npc.key, alt=use_alt))


def _repair_max(item: Item) -> int | None:
    dur = item.durability
    if dur is None:
        return None
    if dur.max_days is not None:
        return int(dur.max_days)
    if dur.max is not None:
        return int(dur.max)
    return None


async def load_village_view(
    catalog: Catalog,
    store: PlayerStore,
    guild_id: int,
    user_id: int,
    *,
    npc_key: str | None = None,
    shop_tab: str = "buy",
    flash: str = "",
    talk_question: str = "",
    talk_response: str = "",
    talk_status: str = "",
    talk_intent: str = "none",
    talk_item_key: str | None = None,
    talk_milieu_key: str | None = None,
    talk_display: str = "none",
    talk_board_keys: list[str] | None = None,
    talk_quantity: int = 1,
    restore_focus: bool = False,
) -> VillageView:
    snap = await store.snapshot(guild_id, user_id)
    env_score = await store.environment_score(guild_id)
    specimens = await store.list_caught(guild_id, user_id)
    announcements = await store.list_village_announcements(guild_id)
    bucket = village_bucket(catalog)
    present = present_npcs(
        catalog, guild_id, skulls=skull_score(catalog, snap), bucket=bucket
    )
    present_keys = {n.key for n in present}
    if restore_focus and npc_key is None:
        focus_key, focus_bucket = await store.village_focus(guild_id, user_id)
        if focus_key and focus_bucket == bucket and focus_key in present_keys:
            npc_key = focus_key
    if npc_key and npc_key not in present_keys:
        flash = flash or "Ce villageois n'est plus là."
        npc_key = None
    bargain = None
    if npc_key:
        bargain = await store.get_village_bargain(
            guild_id, user_id, npc_key, bucket=bucket
        )
    explicit = bool(talk_status or talk_question or talk_response)
    if npc_key and not explicit:
        last = await store.last_village_talk(guild_id, user_id, npc_key, bucket=bucket)
        if last is not None:
            talk_question = last.question
            talk_response = last.response
            talk_status = "done"
            talk_intent = last.intent
            talk_item_key = last.item_key
            talk_milieu_key = last.milieu_key
            talk_display = last.display
            talk_board_keys = last.board_keys
            talk_quantity = last.quantity
    await store.set_village_focus(guild_id, user_id, npc_key, bucket)
    return VillageView(
        catalog,
        snap,
        present=present,
        env_score=env_score,
        specimens=specimens,
        announcements=announcements,
        npc_key=npc_key,
        shop_tab=shop_tab,
        flash=flash,
        talk_question=talk_question,
        talk_response=talk_response,
        talk_status=talk_status,
        talk_intent=talk_intent,
        talk_item_key=talk_item_key,
        talk_milieu_key=talk_milieu_key,
        talk_display=talk_display,
        talk_board_keys=talk_board_keys or [],
        talk_quantity=talk_quantity,
        bargain=bargain,
    )


class VillageView(discord.ui.LayoutView):
    """Place du village : dialogue, le PNJ décide ce qu'il montre."""

    def __init__(
        self,
        catalog: Catalog,
        snap: PlayerSnapshot,
        *,
        present: list[Npc],
        env_score: int,
        specimens: list[CaughtSpecimen],
        announcements: list[VillageAnnouncement],
        npc_key: str | None = None,
        shop_tab: str = "buy",
        flash: str = "",
        talk_question: str = "",
        talk_response: str = "",
        talk_status: str = "",
        talk_intent: str = "none",
        talk_item_key: str | None = None,
        talk_milieu_key: str | None = None,
        talk_display: str = "none",
        talk_board_keys: list[str] | None = None,
        talk_quantity: int = 1,
        bargain: dict | None = None,
    ) -> None:
        super().__init__(timeout=300 if talk_status in {"pending", "streaming"} else 180)
        self.catalog = catalog
        self.snap = snap
        self.present = present
        self.env_score = env_score
        self.specimens = specimens
        self.announcements = announcements
        self.npc_key = npc_key
        self.shop_tab = shop_tab if shop_tab in SHOP_TAB_LABELS else "buy"
        self.talk_question = talk_question
        self.talk_response = talk_response
        self.talk_status = talk_status
        self.talk_intent = talk_intent
        self.talk_item_key = talk_item_key
        self.talk_milieu_key = talk_milieu_key
        self.talk_display = talk_display if talk_display else "none"
        self.talk_board_keys = list(talk_board_keys or [])
        self.talk_quantity = max(1, int(talk_quantity))
        self.bargain = bargain
        self.attachments: list[discord.File] = []

        env_good = environment_is_good(catalog, env_score)
        current = next((n for n in present if n.key == npc_key), None)

        header = discord.ui.TextDisplay("## Village")
        rotates = next_bucket_at(datetime.now(timezone.utc), catalog.game.world)
        purse = format_money(snap.money, catalog.game.money)
        subtitle = discord.ui.TextDisplay(
            f"-# **Place du village** · jusqu'à **{rotates:%H:%M}** · {purse}"
        )
        body = "Personne n'est là pour le moment."
        board = ""
        note = flash
        button_row: discord.ui.ActionRow | None = None

        if current is None:
            lines: list[str] = []
            for npc in present:
                name = npc.name or npc.key
                lines.append(f"**{name}** · {npc_role_label(npc)}")
            body = "\n".join(lines) if lines else body
            note = flash or "Approche-toi. **Parle-leur** · **montre** ce que tu as."
        else:
            name = current.name or current.key
            role = npc_role_label(current)
            filename = npc_portrait_filename(current, env_good=env_good)
            path = catalog.assets_root / "npcs" / filename
            file = asset_file(path)
            title = discord.ui.TextDisplay(title_name(name))
            if file is not None:
                self.attachments.append(file)
                header = section_with_thumbnail(title, file)
            else:
                header = title
            deal = " · **prix négociés**" if self.bargain else ""
            if role and current.description:
                subtitle = discord.ui.TextDisplay(
                    f"-# {purse} · **{role}** · {current.description}{deal}"
                )
            elif role:
                subtitle = discord.ui.TextDisplay(f"-# {purse} · **{role}**{deal}")
            else:
                subtitle = discord.ui.TextDisplay(f"-# {purse}{deal}")
            board = self._display_board(current, env_good=env_good)
            talk_block = self._talk_block(current.name or current.key)
            if not talk_block:
                tod = world_state(catalog.game.world, snap.guild_id, []).time_of_day
                hook = current.hook_for(tod)
                if hook:
                    talk_block = dialogue_turn(
                        current.name or current.key, npc_speech_text(hook)
                    )
            body = talk_block
            actions: list[discord.ui.Button] = [
                _VillagePlaceButton(),
                _VillageTalkButton(),
            ]
            if self.talk_status == "done" and self.talk_intent not in {"", "none"}:
                block = talk_intent_block(
                    catalog,
                    current,
                    snap,
                    specimens,
                    announcements,
                    intent=self.talk_intent,
                    item_key=self.talk_item_key,
                    milieu_key=self.talk_milieu_key,
                    quantity=self.talk_quantity,
                    bargain=self.bargain,
                )
                actions.append(
                    _VillageConfirmButton(
                        self.talk_intent,
                        quantity=self.talk_quantity,
                        disabled=block is not None,
                    )
                )
                if block and not flash:
                    note = f"**{block}.**"
            button_row = discord.ui.ActionRow(*actions)
            if self.talk_status == "pending":
                note = "**Réflexion…**"
            elif self.talk_status == "streaming":
                note = "**Réponse…**"

        if current is None:
            promo = self._promo_block()
            if promo:
                body = f"{promo}\n\n{body}" if body else promo
        children: list = [header, subtitle, discord.ui.Separator()]
        if body:
            children.append(discord.ui.TextDisplay(body))
        elif not board:
            children.append(discord.ui.TextDisplay("…"))
        if board:
            if body:
                children.append(discord.ui.Separator())
            children.append(discord.ui.TextDisplay(board))
        if present:
            prepend_tabs(
                children,
                discord.ui.ActionRow(
                    _VillageNpcSelect(present, current, env_good=env_good)
                ),
            )
        append_controls(children, note=note, button_row=button_row)
        self.add_item(make_container(*children))

    def _promo_block(self) -> str:
        if not self.announcements:
            return ""
        lines = ["**Bonus**"]
        for ann in self.announcements[:3]:
            npc = next((n for n in self.present if n.key == ann.npc_key), None)
            name = (npc.name if npc else None) or ann.npc_key
            effect = modifier_label(ann.modifier) if ann.modifier else ""
            if not effect:
                continue
            left = announcement_remaining_label(ann.ends_at)
            bit = f"**{name}** · {effect}"
            if left:
                bit += f" · {left}"
            lines.append(bit)
        if len(lines) == 1:
            return ""
        return "\n".join(lines)

    def _talk_block(self, speaker: str) -> str:
        if not self.talk_status and not self.talk_response:
            return ""
        question = (self.talk_question or "").strip()
        response = (self.talk_response or "").strip()
        if self.talk_status == "pending":
            said = "*…*"
        elif self.talk_status == "streaming":
            raw = response
            if raw and not raw.endswith("…"):
                raw += "…"
            said = npc_speech_text(raw) if raw else "*…*"
        else:
            said = npc_speech_text(response)
        parts: list[str] = []
        if question:
            parts.append(dialogue_turn("Toi", question))
        if said:
            parts.append(dialogue_turn(speaker, said))
        return "\n\n".join(parts)

    def _revealed_keys(self) -> set[str]:
        keys = set(self.talk_board_keys or [])
        if self.talk_item_key:
            keys.add(self.talk_item_key)
        if self.talk_milieu_key:
            keys.add(self.talk_milieu_key)
        return keys

    def _display_board(self, npc: Npc, *, env_good: bool) -> str:
        mode = self.talk_display
        if mode == "none":
            if npc.role == "travel":
                return self._here_only()
            return ""
        if mode == "stock":
            return self._board_stock(npc)
        if mode == "purse":
            return self._board_purse()
        if mode == "destinations":
            return self._board_destinations()
        if mode == "repairs":
            return self._board_repairs()
        if mode == "env":
            return self._board_env(env_good=env_good)
        if mode == "fossils":
            return self._board_fossils()
        return ""

    def _filter_keys(self, key: str) -> bool:
        return key in self._revealed_keys()

    def _mods(self) -> list:
        return price_modifiers(self.announcements, self.bargain)

    def _board_stock(self, npc: Npc) -> str:
        money = self.catalog.game.money
        mods = self._mods()
        lines: list[str] = []
        for it in shop_stock(self.catalog, npc):
            if not self._filter_keys(it.key):
                continue
            price = apply_named_mult(int(it.economy.buy_price or 0), mods, "buy_mult")
            mark = ""
            if self.talk_item_key == it.key:
                mark = f" · **×{self.talk_quantity}**" if self.talk_quantity > 1 else " · **ça**"
            lines.append(f"{item_display(self.catalog, it.key)} · {format_money(price, money)}{mark}")
        if not lines:
            return ""
        return "**Étal**\n" + "\n".join(lines[:25])

    def _board_purse(self) -> str:
        catalog = self.catalog
        money = catalog.game.money
        mods = self._mods()
        revealed = self._revealed_keys()
        if not revealed:
            return ""
        lines: list[str] = []
        for spec in self.specimens:
            if spec.species_key not in revealed:
                continue
            try:
                species = catalog.get_species(spec.species_key)
            except Exception:
                continue
            if not species.economy.sellable:
                continue
            price = specimen_price(
                catalog, species, spec.length_cm, spec.weight_kg, modifiers=mods
            )
            extra = (
                f" · `{spec.length_cm} cm` · `{spec.weight_kg} kg` · "
                f"{format_money(price, money)}"
            )
            mark = ""
            if self.talk_item_key == spec.species_key:
                mark = f" · **×{self.talk_quantity}**" if self.talk_quantity > 1 else " · **ça**"
            lines.append(species_display(catalog, spec.species_key, extra=f"{extra}{mark}"))
        for stack in self.snap.stacks:
            if stack.item_key not in revealed:
                continue
            try:
                item = catalog.get_item(stack.item_key)
            except Exception:
                continue
            if item.economy.sell_price is None:
                continue
            mark = ""
            if self.talk_item_key == item.key:
                mark = f" · **×{self.talk_quantity}**" if self.talk_quantity > 1 else " · **ça**"
            if item.category == "waste":
                lines.append(
                    self._waste_rate_line(
                        item,
                        qty=stack.quantity,
                        mark=mark,
                        modifiers=mods,
                    )
                )
                continue
            price = apply_named_mult(int(item.economy.sell_price), mods, "sell_mult")
            extra = f" ×{stack.quantity} · {format_money(price, money)}"
            lines.append(item_display(catalog, item.key, extra=f"{extra}{mark}"))
        if not lines:
            return ""
        return "\n".join(lines[:25])

    def _here_line(self) -> str:
        key = self.snap.milieu_key
        dest = self.snap.travel_dest
        rem = travel_remaining_s(self.snap.travel_arrives_at)
        walking = bool(dest and rem is not None and rem > 0)
        if walking and dest:
            try:
                dest_name = self.catalog.get_milieu(dest).name
            except Exception:
                dest_name = dest
            mins = travel_minutes_left(rem or 0)
            if key:
                try:
                    milieu = self.catalog.get_milieu(key)
                    phrase = milieu_at_phrase(milieu.key, milieu.name)
                except Exception:
                    phrase = key
                return (
                    f"**Tu es à {phrase}** · **en route** vers {dest_name} · "
                    f"encore **{mins} min**"
                )
            return f"**En route** vers {dest_name} · encore **{mins} min**"
        if not key:
            return "**Tu n'es nulle part.** Choisis un milieu, ou un passage."
        try:
            milieu = self.catalog.get_milieu(key)
            phrase = milieu_at_phrase(milieu.key, milieu.name)
        except Exception:
            phrase = key
        return f"**Tu es à {phrase}.**"

    def _walk_note(self) -> str:
        return (
            f"-# Marche · **{walk_minutes(self.catalog, self.snap)} min** · "
            f"**gratuite** · /monde"
        )

    def _here_only(self) -> str:
        return "\n\n".join([self._here_line(), self._walk_note()])

    def _board_destinations(self) -> str:
        money = self.catalog.game.money
        mods = self._mods()
        dests: list[str] = []
        for milieu in self.catalog.milieus:
            if not self._filter_keys(milieu.key):
                continue
            if self.snap.milieu_key == milieu.key:
                continue
            mark = " · **ça**" if self.talk_milieu_key == milieu.key else ""
            if self.snap.travel_dest == milieu.key:
                rem = travel_remaining_s(self.snap.travel_arrives_at)
                price = apply_named_mult(
                    passeur_price(self.catalog, remaining_s=rem, snap=self.snap),
                    mods,
                    "travel_mult",
                )
                fare = format_money(price, money) if price else "arrivée"
                dests.append(f"**{milieu.name}** · {fare} · raccourci{mark}")
            else:
                price = apply_named_mult(
                    passeur_price(self.catalog, remaining_s=None, snap=self.snap),
                    mods,
                    "travel_mult",
                )
                dests.append(
                    f"**{milieu.name}** · {format_money(price, money)}{mark}"
                )
        parts = [self._here_line()]
        if dests:
            parts.append("**Passage**\n" + "\n".join(dests))
        parts.append(self._walk_note())
        return "\n\n".join(parts)

    def _board_repairs(self) -> str:
        money = self.catalog.game.money
        mods = self._mods()
        lines: list[str] = []
        for gear in self.snap.gear:
            try:
                item = self.catalog.get_item(gear.item_key)
            except Exception:
                continue
            if not self._filter_keys(item.key):
                continue
            dur = item.durability
            if dur is None or not dur.repairable or dur.repair_cost is None:
                continue
            maximum = _repair_max(item)
            if maximum is None or gear.durability is None or gear.durability >= maximum:
                continue
            extra = _durability_label(item, gear.durability)
            cost = apply_named_mult(int(dur.repair_cost), mods, "repair_mult")
            mark = " · **ça**" if self.talk_item_key == item.key else ""
            lines.append(
                item_display(self.catalog, item.key, extra=f"{extra} · {format_money(cost, money)}{mark}")
            )
        if not lines:
            return ""
        return "**À l'établi**\n" + "\n".join(lines[:25])

    def _waste_rate_line(
        self,
        item,
        *,
        qty: int | None = None,
        mark: str = "",
        modifiers: list | None = None,
        show_price: bool = True,
    ) -> str:
        money = self.catalog.game.money
        mods = modifiers if modifiers is not None else self._mods()
        bits: list[str] = []
        if qty is not None and qty > 1:
            bits.append(f"×{qty}")
        if show_price:
            bits.append(format_money(waste_sell_unit(item, mods), money))
            env = waste_env_points(item)
            if env:
                bits.append(f"**+{env}** note environnementale")
        extra = " · ".join(bits)
        return item_display(self.catalog, item.key, extra=f"{extra}{mark}" if extra else mark)

    def _board_env(self, *, env_good: bool) -> str:
        village = self.catalog.game.village
        pct = environment_pct(self.catalog, self.env_score)
        mood = "sereine" if env_good else "inquiète"
        if environment_is_great(self.catalog, self.env_score):
            waters = "les beaux poissons **affluent**"
        elif environment_is_poor(self.catalog, self.env_score):
            waters = "les beaux poissons se **raréfient**"
        else:
            waters = "les eaux sont **calmes**"
        lines = [
            f"**Note environnementale** · **{pct} %**",
            f"Gaia est **{mood}** · {waters}.",
            f"-# Au-dessus de **{village.environment_great_threshold} %**, "
            f"tout le serveur voit plus de beaux poissons. "
            f"En dessous de **{village.environment_poor_threshold} %**, l'inverse. "
            f"La surpêche dans un même milieu fait baisser la note.",
        ]
        mods = self._mods()
        owned = {s.item_key: s.quantity for s in self.snap.stacks}
        rates: list[str] = []
        for item in cleanup_waste_items(self.catalog):
            if not self._filter_keys(item.key):
                continue
            qty = owned.get(item.key)
            mark = ""
            if self.talk_item_key == item.key:
                mark = f" · **×{self.talk_quantity}**" if self.talk_quantity > 1 else " · **ça**"
            rates.append(self._waste_rate_line(item, qty=qty, mark=mark, modifiers=mods))
        if rates:
            lines.append("\n".join(rates[:25]))
        return "\n".join(lines)

    def _board_fossils(self) -> str:
        skulls = skull_score(self.catalog, self.snap)
        threshold = self.catalog.game.village.skull_summon_threshold
        fossils = next(
            (s.quantity for s in self.snap.stacks if s.item_key == "fossil_in_stone"), 0
        )
        replicas = fossil_replicas(self.catalog)
        owned = self.snap.owned_keys()
        have = sum(1 for it in replicas if it.key in owned)
        return (
            f"**Crânes** · `{skulls}/{threshold}`\n"
            f"**Fossiles dans la pierre** · `{fossils}`\n"
            f"**Répliques** · `{have}/{len(replicas)}`"
        )


class _VillageNpcSelect(discord.ui.Select):
    def __init__(
        self, present: list[Npc], current: Npc | None, *, env_good: bool
    ) -> None:
        options: list[discord.SelectOption] = []
        for npc in present:
            kwargs: dict = {
                "label": (npc.name or npc.key)[:100],
                "value": npc.key,
                "description": npc_role_label(npc)[:100],
                "default": current is not None and npc.key == current.key,
            }
            emoji = _npc_face_emoji(npc, env_good=env_good)
            if emoji is not None:
                kwargs["emoji"] = emoji
            options.append(discord.SelectOption(**kwargs))
        super().__init__(
            placeholder="Parler à…",
            min_values=1,
            max_values=1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, VillageView):
            return
        loaded = await _village_store(interaction)
        if loaded is None:
            return
        store, catalog = loaded
        guild = interaction.guild
        assert guild is not None
        if not interaction.response.is_done():
            await interaction.response.defer()
        nxt = await load_village_view(
            catalog, store, guild.id, interaction.user.id, npc_key=self.values[0]
        )
        await _apply_view(interaction, nxt)


class _VillagePlaceButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="◀ Place",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, VillageView):
            return
        loaded = await _village_store(interaction)
        if loaded is None:
            return
        store, catalog = loaded
        guild = interaction.guild
        assert guild is not None
        if not interaction.response.is_done():
            await interaction.response.defer()
        nxt = await load_village_view(
            catalog, store, guild.id, interaction.user.id, restore_focus=False
        )
        await _apply_view(interaction, nxt)


async def _village_store(interaction: discord.Interaction) -> tuple[PlayerStore, Catalog] | None:
    if interaction.guild is None:
        await edit_error(interaction, "Cette commande s'utilise sur un serveur.")
        return None
    store = getattr(interaction.client, "store", None)
    catalog = getattr(interaction.client, "catalog", None)
    if store is None or catalog is None or not isinstance(store, PlayerStore):
        await edit_error(interaction, "AZURE n'est pas prêt.")
        return None
    assert isinstance(catalog, Catalog)
    return store, catalog


class _VillageTalkButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(style=discord.ButtonStyle.primary, label="Parler")

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, VillageView) or not parent.npc_key:
            return
        npc = next((n for n in parent.present if n.key == parent.npc_key), None)
        if npc is None:
            return
        await interaction.response.send_modal(VillageTalkModal(parent, npc))


def _talk_show_label(npc: Npc) -> tuple[str, str]:
    if npc.role == "shop" and npc.shop_mode == "sell":
        return "Montrer un article", "De son étal"
    if npc.role == "shop" and npc.shop_mode == "buy":
        return "Montrer quelque chose", "À lui vendre"
    if npc.role == "repair":
        return "Montrer le matériel", "Ce qu'il peut regarder"
    if npc.role == "special":
        return "Montrer un déchet", "Pour la note"
    if npc.role == "summon":
        return "Montrer un fossile", "Ce qu'il collectionne"
    return "Montrer", "En rapport avec lui"


def _talk_show_options(
    catalog: Catalog,
    npc: Npc,
    snap: PlayerSnapshot,
    specimens: list[CaughtSpecimen],
) -> list[discord.SelectOption]:
    options: list[discord.SelectOption] = []
    for key in talk_show_keys(catalog, npc, snap=snap, specimens=specimens):
        extra = ""
        try:
            item = catalog.get_item(key)
            label = item.name
            qty = next((s.quantity for s in snap.stacks if s.item_key == key), 0)
            if qty > 1:
                extra = f"×{qty}"
            emoji = _select_emoji(item.key)
        except Exception:
            try:
                species = catalog.get_species(key)
            except Exception:
                continue
            label = species.name
            have = [s for s in specimens if s.species_key == key]
            if have:
                extra = f"{have[0].length_cm:g} cm"
                if len(have) > 1:
                    extra = f"×{len(have)}"
            emoji = _partial_emoji(species_emoji(key))
        kwargs: dict = {"label": label[:100], "value": key}
        if extra:
            kwargs["description"] = extra[:100]
        if emoji is not None:
            kwargs["emoji"] = emoji
        options.append(discord.SelectOption(**kwargs))
    return options[:25]


class VillageTalkModal(discord.ui.Modal, title="Parler"):
    def __init__(self, parent: VillageView, npc: Npc) -> None:
        super().__init__()
        self.npc_key = npc.key
        name = npc.name or npc.key
        self.show: discord.ui.Select | None = None
        options = _talk_show_options(
            parent.catalog, npc, parent.snap, parent.specimens
        )
        if options:
            title, hint = _talk_show_label(npc)
            self.show = discord.ui.Select(
                placeholder="Rien · juste parler",
                min_values=0,
                max_values=1,
                options=options,
                required=False,
            )
            self.add_item(
                discord.ui.Label(text=title[:45], description=hint[:100], component=self.show)
            )
        self.line = discord.ui.TextInput(
            label=f"À {name}"[:45],
            placeholder="Qu'est-ce que tu lui dis ?",
            style=discord.TextStyle.paragraph,
            max_length=400,
            required=True,
        )
        self.add_item(self.line)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Azure")
        handler = getattr(cog, "handle_village_talk", None)
        if handler is None:
            await edit_error(interaction, "AZURE n'est pas prêt.")
            return
        shown = None
        if self.show is not None and self.show.values:
            shown = self.show.values[0]
        await handler(
            interaction,
            npc_key=self.npc_key,
            question=self.line.value.strip(),
            shown_key=shown,
        )


class _VillageConfirmButton(discord.ui.Button):
    def __init__(self, intent: str, *, quantity: int = 1, disabled: bool = False) -> None:
        labels = {
            "buy": "Confirmer l'achat",
            "sell": "Confirmer la vente",
            "repair": "Confirmer la réparation",
            "travel": "Confirmer le passage",
            "exchange": "Confirmer l'échange",
            "cleanup": "Confirmer le nettoyage",
        }
        label = labels.get(intent, "Confirmer")
        if quantity > 1 and intent in {"buy", "sell", "cleanup"}:
            label = f"{label} · ×{quantity}"
        super().__init__(
            style=discord.ButtonStyle.success,
            label=label[:80],
            disabled=disabled,
        )
        self.intent = intent

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, VillageView) or not parent.npc_key:
            return
        loaded = await _village_store(interaction)
        if loaded is None:
            return
        store, catalog = loaded
        guild = interaction.guild
        assert guild is not None
        if not interaction.response.is_done():
            await interaction.response.defer()
        npc = next((n for n in parent.present if n.key == parent.npc_key), None)
        block = talk_intent_block(
            catalog,
            npc,
            parent.snap,
            parent.specimens,
            parent.announcements,
            intent=self.intent,
            item_key=parent.talk_item_key,
            milieu_key=parent.talk_milieu_key,
            quantity=parent.talk_quantity,
            bargain=parent.bargain,
        )
        if block:
            nxt = await load_village_view(
                catalog,
                store,
                guild.id,
                interaction.user.id,
                npc_key=parent.npc_key,
                flash=f"**{block}.**",
            )
            await _apply_view(interaction, nxt)
            return
        try:
            flash = await _apply_talk_intent(
                store,
                catalog,
                guild.id,
                interaction.user.id,
                npc=npc,
                intent=self.intent,
                item_key=parent.talk_item_key,
                milieu_key=parent.talk_milieu_key,
                quantity=parent.talk_quantity,
            )
            await store.clear_village_talk_intent(
                guild.id, interaction.user.id, parent.npc_key
            )
            nxt = await load_village_view(
                catalog, store, guild.id, interaction.user.id,
                npc_key=parent.npc_key, flash=flash,
            )
            await _apply_view(interaction, nxt)
        except PlayerError as exc:
            nxt = await load_village_view(
                catalog,
                store,
                guild.id,
                interaction.user.id,
                npc_key=parent.npc_key,
                flash=f"**{str(exc).rstrip('.')}.**",
            )
            await _apply_view(interaction, nxt)


async def _apply_talk_intent(
    store: PlayerStore,
    catalog: Catalog,
    guild_id: int,
    user_id: int,
    *,
    npc,
    intent: str,
    item_key: str | None,
    milieu_key: str | None,
    quantity: int = 1,
) -> str:
    if intent == "travel":
        if not milieu_key:
            raise PlayerError("dis-lui d'abord où aller")
        before = (await store.snapshot(guild_id, user_id)).money
        changed, new_key, money = await store.travel_to(guild_id, user_id, milieu_key)
        milieu = catalog.get_milieu(new_key)
        phrase = milieu_at_phrase(milieu.key, milieu.name)
        paid = max(0, before - money)
        if changed and paid:
            return f"**Tu es à {phrase}** · {format_money_plain(paid, catalog.game.money)}"
        if changed:
            return f"**Tu es à {phrase}.**"
        return f"**Tu es déjà à {phrase}.**"
    if intent == "buy":
        if not item_key:
            raise PlayerError("dis-lui d'abord quoi acheter")
        seller = npc.key if npc is not None else None
        qty = max(1, int(quantity))
        paid, _money = await store.buy_item(
            guild_id, user_id, item_key, qty, seller_key=seller
        )
        extra = f" ×{qty}" if qty > 1 else ""
        return (
            f"**Acheté** · {item_display(catalog, item_key)}{extra} · "
            f"{format_money_plain(paid, catalog.game.money)}"
        )
    if intent == "sell":
        if not item_key:
            raise PlayerError("dis-lui d'abord quoi vendre")
        try:
            species = catalog.get_species(item_key)
        except Exception:
            species = None
        if species is not None:
            if not species.economy.sellable:
                raise PlayerError("cette prise ne se vend pas")
            qty = max(1, int(quantity))
            specimens = await store.list_caught(guild_id, user_id)
            matches = [s for s in specimens if s.species_key == item_key]
            if not matches:
                raise PlayerError("tu n'as pas cette prise")
            total = 0
            sold = 0
            species_key = item_key
            for spec in matches[:qty]:
                price, species_key, _money = await store.sell_specimen(
                    guild_id, user_id, spec.id
                )
                total += price
                sold += 1
            extra = f" ×{sold}" if sold > 1 else ""
            return (
                f"**Vendu** · {species_display(catalog, species_key)}{extra} · "
                f"{format_money_plain(total, catalog.game.money)}"
            )
        try:
            qty = max(1, int(quantity))
            total, _money, env = await store.sell_item(
                guild_id, user_id, item_key, quantity=qty
            )
        except PlayerError as exc:
            if "instance" not in str(exc):
                raise
            snap = await store.snapshot(guild_id, user_id)
            gear = next((g for g in snap.gear if g.item_key == item_key), None)
            if gear is None:
                raise
            total, _money, env = await store.sell_item(
                guild_id, user_id, item_key, gear_id=gear.id
            )
        extra = f" · +{env} note environnementale" if env else ""
        qty_bit = f" ×{qty}" if qty > 1 else ""
        return (
            f"**Vendu** · {item_display(catalog, item_key)}{qty_bit} · "
            f"{format_money_plain(total, catalog.game.money)}{extra}"
        )
    if intent == "cleanup":
        snap = await store.snapshot(guild_id, user_id)
        sold = 0
        env_total = 0
        money_total = 0
        for stack in list(snap.stacks):
            try:
                item = catalog.get_item(stack.item_key)
            except Exception:
                continue
            if item.category != "waste":
                continue
            if item_key and item.key != item_key:
                continue
            price, _money, env = await store.sell_item(
                guild_id, user_id, item.key, quantity=stack.quantity
            )
            sold += stack.quantity
            env_total += env
            money_total += price
        if sold == 0:
            raise PlayerError("rien à ramasser")
        extra = f" · +{env_total} note environnementale" if env_total else ""
        return f"**Nettoyé** · {sold} · {format_money_plain(money_total, catalog.game.money)}{extra}"
    if intent == "repair":
        if not item_key:
            raise PlayerError("dis-lui d'abord quoi réparer")
        snap = await store.snapshot(guild_id, user_id)
        gear = next((g for g in snap.gear if g.item_key == item_key), None)
        if gear is None:
            raise PlayerError("tu n'as pas cet équipement")
        cost, _money = await store.repair_gear(guild_id, user_id, gear.id)
        return f"**Réparé** · {item_display(catalog, item_key)} · {format_money_plain(cost, catalog.game.money)}"
    if intent == "exchange":
        replica = await store.exchange_fossil(guild_id, user_id)
        return f"**Échangé** · {item_display(catalog, replica)}"
    raise PlayerError("rien à confirmer")


class VillageAnnounceView(discord.ui.LayoutView):
    """Annonce publique d'un villageois présent."""

    def __init__(
        self,
        catalog: Catalog,
        npc: Npc,
        text: str,
        *,
        env_good: bool,
        note: str = "",
    ) -> None:
        super().__init__(timeout=None)
        self.attachments: list[discord.File] = []
        name = npc.name or npc.key
        filename = npc_portrait_filename(npc, env_good=env_good)
        path = catalog.assets_root / "npcs" / filename
        file = asset_file(path)
        title = discord.ui.TextDisplay(title_name(name))
        header: discord.ui.Item = title
        if file is not None:
            self.attachments.append(file)
            header = section_with_thumbnail(title, file)
        children: list = [
            header,
            discord.ui.TextDisplay("-# **Annonce du village**"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(text),
        ]
        append_controls(children, note=note)
        self.add_item(make_container(*children))


class ItemInspectView(discord.ui.LayoutView):
    """Fiche d'un item : thumbnail PNG, nom en titre, pas d'emoji du même asset."""

    def __init__(self, catalog: Catalog, item: Item, *, admin: bool = False) -> None:
        super().__init__(timeout=120)
        self.attachments: list[discord.File] = []

        name_body = discord.ui.TextDisplay(title_name(item.name))
        header: discord.ui.Item = name_body
        path = catalog.assets_root / "items" / item.sprite
        file = asset_file(path)
        if file is not None:
            self.attachments.append(file)
            header = section_with_thumbnail(name_body, file)
        else:
            header = discord.ui.TextDisplay(
                with_emoji(item_emoji(item.key), f"**{item.name}**")
            )

        cat_label = CATEGORY_LABELS.get(item.category, item.category)
        bits = [f"`{item.key}`", cat_label]
        if not item.enabled:
            bits.append("désactivé")
        sub = discord.ui.TextDisplay("-# " + " · ".join(bits))

        details: list[str] = []
        eq = item.equipment
        if eq is not None and eq.equippable:
            slot = SLOT_LABELS.get(eq.slot or "", eq.slot or "—")
            details.append(f"**Équipement** · {slot}")
            if eq.capture_method:
                details.append(f"**Capture** · {eq.capture_method}")
        dur = item.durability
        if dur is not None:
            if dur.max_days is not None or dur.unit == "days":
                days = dur.max_days if dur.max_days is not None else "—"
                details.append(f"**Durabilité** · {days} j")
            elif dur.max is not None:
                details.append(f"**Durabilité** · {dur.max} usages")
        buy = item.economy.buy_price
        sell = item.economy.sell_price
        has_price = buy is not None or sell is not None
        if buy is not None:
            details.append(f"**Achat** · {format_money(buy, catalog.game.money)}")
        if sell is not None:
            details.append(f"**Vente** · {format_money(sell, catalog.game.money)}")
        if admin and item.sources:
            details.append("**Sources** · " + ", ".join(f"`{s}`" for s in item.sources))

        flavor: list[str] = []
        desc = italic_text(item.description)
        lore = italic_text(item.lore)
        if desc:
            flavor.append(desc)
        if lore:
            flavor.append(lore)

        children: list = [header, sub]
        if flavor:
            children += [discord.ui.Separator(), discord.ui.TextDisplay("\n\n".join(flavor))]
        if details:
            children += [discord.ui.Separator(), discord.ui.TextDisplay("\n".join(details))]
        if has_price:
            children += [
                discord.ui.TextDisplay(
                    "-# Prix indicatifs — varient selon le marchand et le contexte."
                )
            ]
        self.add_item(make_container(*children))


class NoticeView(discord.ui.LayoutView):
    def __init__(self, title: str, body: str, *, note: str = "") -> None:
        super().__init__(timeout=60)
        children: list = [
            discord.ui.TextDisplay(f"## {title}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(body),
        ]
        if note:
            text = note if note.startswith("-#") else f"-# {note}"
            children += [discord.ui.Separator(), discord.ui.TextDisplay(text)]
        self.add_item(make_container(*children))


class CatalogView(discord.ui.LayoutView):
    def __init__(self, catalog: Catalog, bound: int, total: int) -> None:
        super().__init__(timeout=120)
        p = catalog.game.player
        starter = catalog.items_by_source("starter", enabled_only=True)
        disabled = [it.key for it in catalog.items if not it.enabled]
        starter_line = ", ".join(item_display(catalog, it.key) for it in starter) or "—"
        disabled_line = ", ".join(f"`{k}`" for k in disabled) or "—"
        milieus = ", ".join(f"`{m.key}`" for m in catalog.milieus)
        children = [
            discord.ui.TextDisplay("## Catalogue"),
            discord.ui.TextDisplay(f"-# {catalog.summary()}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(
                f"**Départ** · énergie {p.energy_start}/{p.energy_max} · {format_money(p.money_start, catalog.game.money)}\n"
                f"**Milieux** · {milieus}\n"
                f"**Starter** · {starter_line}\n"
                f"**Désactivés** · {disabled_line}"
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay(f"**Emojis** · {bound}/{total}"),
        ]
        self.add_item(make_container(*children))


class EmojisGalleryView(discord.ui.LayoutView):
    """Tous les emojis d'application liés, paginés (pas de thumbnail)."""

    def __init__(
        self,
        *,
        title: str,
        summary: str,
        pages: list[list[tuple[str, list[str]]]],
        page: int = 0,
        errors: str = "",
    ) -> None:
        super().__init__(timeout=180)
        self.title = title
        self.summary = summary
        self.pages = pages
        self.page = page
        self.errors = errors
        total_pages = max(1, len(pages))
        index = max(0, min(page, total_pages - 1))
        self.page = index

        children: list = [
            discord.ui.TextDisplay(f"## {title}"),
            discord.ui.TextDisplay(f"-# {summary}" + (f" · page {index + 1}/{total_pages}" if total_pages > 1 else "")),
        ]
        if pages:
            blocks: list[str] = []
            for heading, codes in pages[index]:
                blocks.append(f"**{heading}**\n" + " ".join(codes))
            children += [discord.ui.Separator(), discord.ui.TextDisplay("\n\n".join(blocks))]
        else:
            children += [discord.ui.Separator(), discord.ui.TextDisplay("Aucun emoji lié.")]

        if errors:
            children += [discord.ui.Separator(), discord.ui.TextDisplay(errors)]
        button_row = None
        if total_pages > 1:
            button_row = discord.ui.ActionRow(
                _GalleryNavButton(delta=-1, disabled=index <= 0, label="◀"),
                _GalleryNavButton(delta=1, disabled=index >= total_pages - 1, label="▶"),
            )
        append_controls(children, button_row=button_row)
        self.add_item(make_container(*children))

    @classmethod
    def from_catalog(
        cls,
        catalog: Catalog,
        *,
        title: str,
        summary: str,
        errors: str = "",
        page: int = 0,
    ) -> EmojisGalleryView:
        pages = paginate_gallery(gallery_sections(catalog))
        return cls(title=title, summary=summary, pages=pages, page=page, errors=errors)


class _GalleryNavButton(discord.ui.Button):
    def __init__(self, *, delta: int, disabled: bool, label: str) -> None:
        super().__init__(style=discord.ButtonStyle.secondary, label=label, disabled=disabled)
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, EmojisGalleryView):
            return
        nxt = EmojisGalleryView(
            title=parent.title,
            summary=parent.summary,
            pages=parent.pages,
            page=parent.page + self.delta,
            errors=parent.errors,
        )
        await interaction.response.edit_message(view=nxt)
