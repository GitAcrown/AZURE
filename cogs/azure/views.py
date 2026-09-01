"""UI Components v2 AZURE — LayoutViews profil / notices / village."""

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
    SELECT_MAX,
    append_controls,
    button_label,
    edit_error,
    make_container,
    prepend_tabs,
    section_with_thumbnail,
    select_desc,
    select_label,
    text_display,
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
    energy_amount,
)
from common.inspect import (
    inspect_item_text,
    inspect_species_text,
    species_context_line,
    species_where_text,
)
from common.money import format_money, format_money_plain
from common.onboarding import slide_at, slide_count
from common.pitch import pitch_blocks, pitch_tagline, pitch_title
from common.daily import daily_counters_text, daily_place_block
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
from common.fishing import cast_energy_parts, item_is_gem
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
    cleanup_take,
    modifier_label,
    passeur_price,
    present_npcs,
    price_modifiers,
    shop_stock,
    talk_intent_block,
    talk_select_description,
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
    "hook": "Hameçon",
    "bait": "Appât",
    "objet": "Objet",
}

DISPLAY_SLOTS = ("tool", "hook", "bait", "objet")
ROD_ONLY_SLOTS = frozenset({"hook", "bait"})

CATEGORY_LABELS = {
    "tool": "Outil",
    "hook": "Hameçon",
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

HUB_TAB_LABELS = {
    "profil": "Profil",
    "sac": "Sac",
    "dex": "Dex",
}

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


def _durability_plain(item: Item, remaining: int | None) -> str:
    """Durabilité sans markdown — pour les descriptions de select."""
    if remaining is None or item.durability is None:
        return ""
    dur = item.durability
    if dur.max_days is not None or dur.unit == "days":
        return f"{remaining} j"
    if dur.max is not None:
        return f"{remaining}/{dur.max} usages"
    return ""


def _durability_label(item: Item, remaining: int | None) -> str:
    if remaining is None or item.durability is None:
        return ""
    dur = item.durability
    if dur.max_days is not None or dur.unit == "days":
        return f" · `{remaining} j`"
    if dur.max is not None:
        return f" · `{remaining}/{dur.max}` usages"
    return ""


def _equipped_key(eq) -> str | None:
    if eq is None:
        return None
    if eq.gear is not None:
        return eq.gear.item_key
    return eq.item_key


def _tool_method(catalog: Catalog, snap: PlayerSnapshot) -> str | None:
    key = _equipped_key(snap.equipped.get("tool"))
    if not key:
        return None
    try:
        item = catalog.get_item(key)
    except Exception:
        return None
    eq = item.equipment
    return eq.capture_method if eq is not None else None


def _display_slots_for(catalog: Catalog, snap: PlayerSnapshot) -> tuple[str, ...]:
    if _tool_method(catalog, snap) == "net":
        return tuple(s for s in DISPLAY_SLOTS if s not in ROD_ONLY_SLOTS)
    return DISPLAY_SLOTS


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


def _nav_arrow_kwargs(delta: int, *, disabled: bool) -> dict:
    key = "LEFT" if delta < 0 else "RIGHT"
    fallback = "◀" if delta < 0 else "▶"
    kwargs: dict = {
        "style": discord.ButtonStyle.secondary,
        "disabled": disabled,
    }
    emoji = _partial_emoji(ui_emoji(key))
    if emoji is not None:
        kwargs["emoji"] = emoji
    else:
        kwargs["label"] = fallback
    return kwargs


def _left_action_kwargs(label: str, *, disabled: bool = False) -> dict:
    kwargs: dict = {
        "style": discord.ButtonStyle.secondary,
        "disabled": disabled,
        "label": button_label(label),
    }
    emoji = _partial_emoji(ui_emoji("LEFT"))
    if emoji is not None:
        kwargs["emoji"] = emoji
    else:
        kwargs["label"] = button_label(f"◀ {label}")
    return kwargs


def _is_collectible_key(catalog: Catalog, item_key: str) -> bool:
    try:
        return item_is_collectible(catalog.get_item(item_key))
    except Exception:
        return False


def _inventory_parts(
    catalog: Catalog, snap: PlayerSnapshot, *, collectibles: bool | None = False
) -> list[str]:
    equipped_ids = {eq.gear_id for eq in snap.equipped.values() if eq.gear_id is not None}
    parts: list[str] = []
    for stack in snap.stacks:
        if (
            collectibles is not None
            and _is_collectible_key(catalog, stack.item_key) != collectibles
        ):
            continue
        extra = f" ×{stack.quantity}" if stack.quantity > 1 and not _is_badge_item(catalog, stack.item_key) else ""
        parts.append(item_display(catalog, stack.item_key, extra=extra))
    for gear in snap.gear:
        if gear.id in equipped_ids:
            continue
        if (
            collectibles is not None
            and _is_collectible_key(catalog, gear.item_key) != collectibles
        ):
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


def _is_badge_item(catalog: Catalog, item_key: str) -> bool:
    try:
        item = catalog.get_item(item_key)
    except Exception:
        return False
    if item_is_gem(item):
        return True
    col = item.collection
    return col is not None and col.group == "fossil_replicas"


def _badge_emojis(catalog: Catalog, snap: PlayerSnapshot, items: list[Item]) -> str:
    if not items:
        return ""
    owned = snap.owned_keys()
    bits: list[str] = []
    for it in items:
        has = it.key in owned
        code = (item_emoji(it.key, shadow=not has) or "").strip()
        if not code:
            code = (item_emoji(it.key, shadow=has) or "").strip()
        bits.append(code or ("✦" if has else "·"))
    return " ".join(bits)


def _gem_items(catalog: Catalog) -> list[Item]:
    return _collectible_group(catalog, "gemstones")


def _trophy_block(catalog: Catalog, snap: PlayerSnapshot) -> str:
    gems = _badge_emojis(catalog, snap, _gem_items(catalog))
    fossils = _badge_emojis(
        catalog, snap, _collectible_group(catalog, "fossil_replicas")
    )
    lines: list[str] = []
    row = "   ".join(part for part in (gems, fossils) if part)
    if row:
        lines.append(row)
    if snap.archaeology_points:
        lines.append(f"**Archéologie** · **{snap.archaeology_points}**")
    return "\n".join(lines)


def _collection_block(catalog: Catalog, snap: PlayerSnapshot) -> str:
    return f"**Dex** · {snap.dex_found}/{snap.dex_total}"


def _equipped_lines(catalog: Catalog, snap: PlayerSnapshot) -> list[str]:
    lines: list[str] = []
    for slot in _display_slots_for(catalog, snap):
        label = SLOT_LABELS[slot]
        eq = snap.equipped.get(slot)
        key = _equipped_key(eq)
        if not key:
            lines.append(f"**{label}** · —")
            continue
        extra = ""
        try:
            item = catalog.get_item(key)
            extra = _durability_label(
                item, eq.gear.durability if eq and eq.gear else None
            )
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


def _is_food_item(item: Item) -> bool:
    if item.consumable is None or not item.consumable.consumed_on_use:
        return False
    effects = item.effects or {}
    return "restore_energy_pct" in effects or "max_energy_bonus_pct" in effects


def _food_stacks(catalog: Catalog, snap: PlayerSnapshot) -> list[tuple[Item, int]]:
    out: list[tuple[Item, int]] = []
    for stack in snap.stacks:
        if stack.quantity <= 0:
            continue
        try:
            item = catalog.get_item(stack.item_key)
        except Exception:
            continue
        if _is_food_item(item):
            out.append((item, stack.quantity))
    return out


def _eat_options(catalog: Catalog, snap: PlayerSnapshot) -> list[discord.SelectOption]:
    options: list[discord.SelectOption] = []
    for item, qty in _food_stacks(catalog, snap):
        effects = item.effects or {}
        if "restore_energy_pct" in effects:
            try:
                desc = f"+{int(round(float(effects['restore_energy_pct']) * 100))} % énergie"
            except (TypeError, ValueError):
                desc = "énergie"
        elif "max_energy_bonus_pct" in effects:
            try:
                desc = f"+{int(round(float(effects['max_energy_bonus_pct']) * 100))} % énergie max"
            except (TypeError, ValueError):
                desc = "énergie max"
        else:
            desc = "consommer"
        extra = f" ×{qty}" if qty > 1 else ""
        kwargs: dict = {
            "label": select_label(f"{item.name}{extra}"),
            "value": item.key[:100],
            "description": select_desc(desc),
        }
        emoji = _select_emoji(item.key)
        if emoji is not None:
            kwargs["emoji"] = emoji
        options.append(discord.SelectOption(**kwargs))
        if len(options) >= SELECT_MAX:
            break
    return options


def _hub_tab_row(active: str) -> discord.ui.ActionRow:
    options = [
        discord.SelectOption(label=label, value=key, default=key == active)
        for key, label in HUB_TAB_LABELS.items()
    ]
    return discord.ui.ActionRow(_HubTabSelect(options))


class OnboardingView(discord.ui.LayoutView):
    """Diaporama lancé à la première commande, jusqu'à « C'est parti »."""

    def __init__(self, catalog: Catalog, *, page: int = 0) -> None:
        super().__init__(timeout=600)
        self.catalog = catalog
        total = slide_count()
        self.page = max(0, min(int(page), total - 1))
        slide = slide_at(self.page)
        last = self.page >= total - 1
        children: list = [
            discord.ui.TextDisplay(f"## {slide.title}"),
            discord.ui.TextDisplay(f"-# {self.page + 1} / {total}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(slide.body),
        ]
        buttons: list = [_OnboardNavButton(delta=-1, disabled=self.page <= 0)]
        if last:
            buttons.append(_OnboardStartButton())
        else:
            buttons.append(_OnboardNavButton(delta=1, disabled=False))
        append_controls(children, button_row=discord.ui.ActionRow(*buttons))
        self.add_item(make_container(*children))


class PubView(discord.ui.LayoutView):
    """Présentation publique : une carte, pour ceux qui ne jouent pas encore."""

    def __init__(self, catalog: Catalog) -> None:
        super().__init__(timeout=None)
        children: list = [
            discord.ui.TextDisplay(pitch_title()),
            discord.ui.TextDisplay(pitch_tagline()),
        ]
        for block in pitch_blocks(catalog):
            children += [discord.ui.Separator(), discord.ui.TextDisplay(block)]
        self.add_item(make_container(*children))


class _OnboardNavButton(discord.ui.Button):
    def __init__(self, *, delta: int, disabled: bool) -> None:
        super().__init__(**_nav_arrow_kwargs(delta, disabled=disabled))
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, OnboardingView):
            return
        nxt = OnboardingView(parent.catalog, page=parent.page + self.delta)
        await interaction.response.edit_message(view=nxt)


class _OnboardStartButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(style=discord.ButtonStyle.primary, label="C'est parti")

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, OnboardingView):
            return
        guild = interaction.guild
        if guild is None:
            await edit_error(interaction, "Cette commande s'utilise sur un serveur.")
            return
        store = getattr(interaction.client, "store", None)
        if store is None:
            await edit_error(interaction, "AZURE n'est pas prêt.")
            return
        assert isinstance(store, PlayerStore)
        await store.complete_onboarding(guild.id, interaction.user.id)
        await interaction.response.edit_message(
            view=await load_monde_view(
                parent.catalog,
                store,
                guild.id,
                interaction.user.id,
                flash="**Choisis un milieu.** Premier aller : **immédiat**.",
            )
        )


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
        self.hub_tab = "profil"

        milieu = _milieu_profile_line(catalog, snap)
        equipped_lines = _equipped_lines(catalog, snap)

        subtitle = f"-# {display_name}"
        if snap.created:
            subtitle += " · nouveau pêcheur"

        bar = _energy_bar(snap.energy, snap.energy_max)
        energy_line = f"**Énergie** · `{bar}` {snap.energy}/{snap.energy_max}"
        if snap.coffee_minutes:
            pct = int(round(snap.coffee_pct * 100))
            energy_line += f"\n-# Café · +{pct}% énergie max · encore {snap.coffee_minutes} min"
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
        trophies = _trophy_block(catalog, snap)
        if trophies:
            children += [
                discord.ui.Separator(),
                discord.ui.TextDisplay(trophies),
            ]
        arrived = travel_arrival_flash(catalog, snap)
        if arrived:
            children += [discord.ui.Separator(), discord.ui.TextDisplay(arrived)]
        options = _equip_options(catalog, snap)
        eat = _eat_options(catalog, snap)
        if flash:
            note = flash
        elif options and eat:
            note = "Un seul **objet** actif. **Manger** recharge l'énergie."
        elif options:
            if _tool_method(catalog, snap) == "net":
                note = "Un seul **objet** actif. Le filet n'utilise pas d'hameçon ni d'appât."
            else:
                note = "Un seul **objet** actif. Change canne, hameçon, appât ou objet."
        elif eat:
            note = "**Manger** pour récupérer de l'énergie."
        else:
            note = "Rien à équiper, rien à manger."
        prepend_tabs(children, _hub_tab_row("profil"))
        append_controls(
            children,
            note=note,
            select_row=discord.ui.ActionRow(_EquipSelect(options)) if options else None,
            extra_select_row=discord.ui.ActionRow(_EatSelect(eat)) if eat else None,
        )
        self.add_item(make_container(*children))


def _equip_options(catalog: Catalog, snap: PlayerSnapshot) -> list[discord.SelectOption]:
    visible = set(_display_slots_for(catalog, snap))
    slot_rank = {slot: i for i, slot in enumerate(DISPLAY_SLOTS)}
    rows: list[tuple[int, int, discord.SelectOption]] = []

    def add(slot: str, equipped: bool, option: discord.SelectOption) -> None:
        if slot not in visible:
            return
        rows.append((slot_rank.get(slot, 99), 0 if equipped else 1, option))

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
        desc_parts = ["RETIRER", SLOT_LABELS[slot]]
        if eq is not None and eq.gear is not None:
            try:
                item = catalog.get_item(eq.gear.item_key)
                plain = _durability_plain(item, eq.gear.durability)
                if plain:
                    desc_parts.append(plain)
            except Exception:
                pass
        kwargs: dict = {
            "label": select_label(item_name or SLOT_LABELS[slot]),
            "value": f"unequip:{slot}"[:100],
            "description": select_desc(" · ".join(desc_parts)),
        }
        emoji = _select_emoji(_equipped_key(eq))
        if emoji is not None:
            kwargs["emoji"] = emoji
        add(slot, True, discord.SelectOption(**kwargs))
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
        slot = eq.slot or ""
        slot_label = SLOT_LABELS.get(slot, slot or "?")
        plain = _durability_plain(item, gear.durability)
        desc = slot_label if not plain else f"{slot_label} · {plain}"
        kwargs = {
            "label": select_label(item.name),
            "value": f"gear:{gear.id}"[:100],
            "description": select_desc(desc),
        }
        emoji = _select_emoji(item.key)
        if emoji is not None:
            kwargs["emoji"] = emoji
        add(slot, False, discord.SelectOption(**kwargs))
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
            "label": select_label(item.name),
            "value": f"bait:{item.key}"[:100],
            "description": select_desc(f"Appât · ×{stack.quantity}"),
        }
        emoji = _select_emoji(item.key)
        if emoji is not None:
            kwargs["emoji"] = emoji
        add("bait", False, discord.SelectOption(**kwargs))
    rows.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in rows][:SELECT_MAX]


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
        if not interaction.response.is_done():
            await interaction.response.defer()
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
            nxt = await load_player_hub(
                catalog,
                store,
                guild.id,
                interaction.user.id,
                interaction.user.display_name,
                tab="profil",
                flash=f"**{str(exc).rstrip('.')}.**",
            )
            await _apply_view(interaction, nxt)
            return
        nxt = await load_player_hub(
            catalog,
            store,
            guild.id,
            interaction.user.id,
            interaction.user.display_name,
            tab="profil",
            flash=flash,
        )
        await _apply_view(interaction, nxt)


class _EatSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(
            placeholder="Manger…",
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
        if not interaction.response.is_done():
            await interaction.response.defer()
        item_key = self.values[0]
        try:
            energy, energy_max = await store.consume_item(
                guild.id, interaction.user.id, item_key
            )
            flash = (
                f"{item_display(catalog, item_key)} · **énergie** `{energy}/{energy_max}`"
            )
        except PlayerError as exc:
            flash = f"**{str(exc).rstrip('.')}.**"
        nxt = await load_player_hub(
            catalog,
            store,
            guild.id,
            interaction.user.id,
            interaction.user.display_name,
            tab="profil",
            flash=flash,
        )
        await _apply_view(interaction, nxt)


class _HubTabSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Onglet…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await edit_error(interaction, "Cette commande s'utilise sur un serveur.")
            return
        store = getattr(interaction.client, "store", None)
        catalog = getattr(interaction.client, "catalog", None)
        if store is None or catalog is None or not isinstance(store, PlayerStore):
            await edit_error(interaction, "AZURE n'est pas prêt.")
            return
        assert isinstance(catalog, Catalog)
        if not interaction.response.is_done():
            await interaction.response.defer()
        nxt = await load_player_hub(
            catalog,
            store,
            guild.id,
            interaction.user.id,
            interaction.user.display_name,
            tab=self.values[0],
        )
        await _apply_view(interaction, nxt)



def monde_cast_cost_bit(catalog: Catalog, weather_key: str, *, ignore: bool) -> str:
    base, extra = cast_energy_parts(catalog, weather_key, ignore=ignore)
    if extra:
        return f"{energy_amount(base + extra)} (**+{extra}** énergie météo)"
    return energy_amount(base)


def monde_here_line(
    catalog: Catalog,
    snap: PlayerSnapshot,
    *,
    state,
    walking: bool,
    dest: str | None,
    walk_mins: int,
) -> str:
    current_key = snap.milieu_key
    if not current_key:
        return (
            "Tu n'es **nulle part**. Choisis un milieu ci-dessous — le premier "
            "aller est **immédiat**."
        )
    try:
        milieu = catalog.get_milieu(current_key)
        phrase = milieu_at_phrase(milieu.key, milieu.name)
    except Exception:
        phrase = current_key
    weather = state.weathers.get(current_key)
    bits = [f"📍 **Tu es à {phrase}**"]
    if weather is not None:
        bits.append(weather_display(weather))
    bits.append(time_label(state.time_of_day))
    line = " · ".join(bits)
    line += f"\n⚡ **Énergie** · {snap.energy}/{snap.energy_max}"
    if walking and dest:
        try:
            dest_name = catalog.get_milieu(dest).name
        except Exception:
            dest_name = dest
        line += f"\n🚶 **En route** vers {dest_name} · encore **{walk_mins} min** — pêche impossible tant que tu marches"
    return line


def monde_travel_note(catalog: Catalog, snap: PlayerSnapshot) -> str:
    minutes = walk_minutes(catalog, snap)
    fare = passeur_price(catalog, remaining_s=None, snap=snap)
    fare_txt = format_money(fare, catalog.game.money)
    if not snap.milieu_key:
        return (
            f"Premier milieu : **immédiat**. Ensuite, **marche gratuite** "
            f"(**{minutes} min**). Pour arriver tout de suite : passeur au "
            f"**/village** ({fare_txt})."
        )
    return (
        f"Marche **gratuite** · **{minutes} min**. Pour arriver tout de suite : "
        f"passeur au **/village** ({fare_txt})."
    )


def monde_presence_bit(count: int) -> str:
    if count < 1:
        return ""
    if count == 1:
        return "**1 pêcheur**"
    return f"**{count} pêcheurs**"


async def load_monde_view(
    catalog: Catalog,
    store: PlayerStore,
    guild_id: int,
    user_id: int,
    *,
    flash: str = "",
    debug: bool = False,
) -> MondeView:
    snap = await store.snapshot(guild_id, user_id)
    env_score = await store.environment_score(guild_id)
    presence = await store.milieu_presence(guild_id)
    return MondeView(
        catalog,
        snap,
        env_score=env_score,
        debug=debug,
        flash=flash,
        presence=presence,
    )


class MondeView(discord.ui.LayoutView):
    """Carte : où tu es, ce que ça change pour pêcher, comment y aller."""

    def __init__(
        self,
        catalog: Catalog,
        snap: PlayerSnapshot,
        *,
        env_score: int = 50,
        debug: bool = False,
        flash: str = "",
        presence: dict[str, int] | None = None,
    ) -> None:
        super().__init__(timeout=180)
        self.debug = debug
        self.env_score = env_score
        current_key = snap.milieu_key
        dest = snap.travel_dest
        remaining = travel_remaining_s(snap.travel_arrives_at)
        walking = bool(dest and remaining is not None and remaining > 0)
        keys = [m.key for m in catalog.milieus]
        state = world_state(catalog.game.world, snap.guild_id, keys)
        clock = state.at.strftime("%H:%M")
        nxt_clock = state.next_bucket_at.strftime("%H:%M")
        walk_mins = travel_minutes_left(remaining) if walking and remaining is not None else 0
        effects = collect_owned_effects(catalog, snap.gear, snap.stacks, snap.equipped)
        ignore_weather = bool(effects.get("ignore_bad_weather_fatigue_penalty"))
        ignore_night = bool(effects.get("ignore_night_fishing_success_penalty"))
        forecast = bool(effects.get("destination_weather_forecast_minutes"))

        env_pct = environment_pct(catalog, env_score)
        now_lines = [
            "**🕐 Horloge du serveur** — la même pour tout le monde",
            f"{season_label(state.season)} · {time_label(state.time_of_day)} · `{clock}`",
            f"Météo : change pour **tous les milieux** à `{nxt_clock}`",
        ]
        if state.time_of_day == "night":
            if ignore_night:
                now_lines.append("🌙 Nuit · ta lanterne ignore le malus de réussite")
            else:
                now_lines.append("🌙 Nuit · prises plus rares (une lanterne annule ce malus)")
        env_line = f"🌱 **Note environnementale** · {env_pct}/100"
        if environment_is_great(catalog, env_score):
            env_line += " · les beaux poissons **affluent** pour tout le serveur"
        elif environment_is_poor(catalog, env_score):
            env_line += " · les beaux poissons se **raréfient** pour tout le serveur"
        now_lines.append(env_line)

        milieu_lines: list[str] = ["**🌊 Milieux** — coût affiché = énergie pour **1 lancer** `/pecher`"]
        for milieu in catalog.milieus:
            weather = state.weathers[milieu.key]
            bits = [
                f"**{milieu.name}**",
                weather_display(weather),
                f"🎣 {monde_cast_cost_bit(catalog, weather.key, ignore=ignore_weather)}",
            ]
            if current_key == milieu.key:
                bits.append("📍 ici")
            if walking and dest == milieu.key:
                bits.append(f"🚶 en route · encore **{walk_mins} min**")
            if forecast:
                nxt_weather = weather_at(
                    snap.guild_id, milieu.key, state.next_bucket_at, catalog.game.world
                )
                bits.append(f"dans 1 h → {weather_display(nxt_weather)}")
            here = monde_presence_bit((presence or {}).get(milieu.key, 0))
            if here:
                bits.append(f"👥 {here}")
            milieu_lines.append(" · ".join(bits))

        legend = (
            "-# 📍 tu y es · 🚶 en route · 🎣 énergie par lancer · 👥 pêcheurs "
            "présents · 🌱 qualité de l'eau, influence les prises rares"
        )

        children: list = [
            discord.ui.TextDisplay("## Monde"),
            discord.ui.TextDisplay(
                monde_here_line(
                    catalog,
                    snap,
                    state=state,
                    walking=walking,
                    dest=dest,
                    walk_mins=walk_mins,
                )
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay("\n".join(now_lines)),
            discord.ui.Separator(),
            discord.ui.TextDisplay("\n".join(milieu_lines)),
            discord.ui.TextDisplay(legend),
        ]
        options: list[discord.SelectOption] = []
        selected = dest if walking else None
        minutes = walk_minutes(catalog, snap)
        first = current_key is None
        for m in catalog.milieus:
            if current_key == m.key:
                continue
            opt_kwargs: dict = {
                "label": select_label(m.name),
                "value": m.key[:100],
                "default": selected is not None and m.key == selected,
            }
            if walking and dest == m.key:
                opt_kwargs["description"] = select_desc(
                    f"en route · encore {walk_mins} min"
                )
            elif first:
                opt_kwargs["description"] = select_desc("immédiat")
            else:
                opt_kwargs["description"] = select_desc(f"marche · {minutes} min")
            options.append(discord.SelectOption(**opt_kwargs))
            if len(options) >= SELECT_MAX:
                break
        note = flash or travel_arrival_flash(catalog, snap) or monde_travel_note(catalog, snap)
        if debug:
            debug_note = f"bucket `{state.bucket}` · prochaine rotation `{nxt_clock}`"
            note = f"{note} · {debug_note}" if note else debug_note
        can_fish_here = bool(current_key) and not walking
        append_controls(
            children,
            note=note,
            button_row=(
                discord.ui.ActionRow(_PecherHereButton())
                if can_fish_here
                else None
            ),
            select_row=(
                discord.ui.ActionRow(
                    _MilieuSelect(options, debug=debug, env_score=env_score)
                )
                if options
                else None
            ),
        )
        self.add_item(make_container(*children))


class _PecherHereButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(style=discord.ButtonStyle.primary, label="Pêcher ici")

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await edit_error(interaction, "Cette commande s'utilise sur un serveur.")
            return
        store = getattr(interaction.client, "store", None)
        catalog = getattr(interaction.client, "catalog", None)
        if store is None or catalog is None or not isinstance(store, PlayerStore):
            await edit_error(interaction, "AZURE n'est pas prêt.")
            return
        assert isinstance(catalog, Catalog)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await start_cast_flow(interaction, catalog, store)


class _MilieuSelect(discord.ui.Select):
    def __init__(
        self,
        options: list[discord.SelectOption],
        *,
        debug: bool = False,
        env_score: int = 50,
    ) -> None:
        super().__init__(
            placeholder="Aller à…",
            min_values=1,
            max_values=1,
            options=options,
        )
        self._debug = debug
        self._env_score = env_score

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
        if not interaction.response.is_done():
            await interaction.response.defer()
        key = self.values[0]
        try:
            changed, new_key = await store.set_milieu(guild.id, interaction.user.id, key)
        except PlayerError as exc:
            await _apply_view(
                interaction,
                await load_monde_view(
                    catalog,
                    store,
                    guild.id,
                    interaction.user.id,
                    debug=self._debug,
                    flash=f"**{str(exc).rstrip('.')}.**",
                ),
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
        await _apply_view(
            interaction,
            await load_monde_view(
                catalog,
                store,
                guild.id,
                interaction.user.id,
                debug=self._debug,
                flash=flash,
            ),
        )



async def _apply_view(interaction: discord.Interaction, view: discord.ui.LayoutView) -> None:
    kwargs: dict = {"view": view}
    files = getattr(view, "attachments", None)
    if files:
        kwargs["attachments"] = files
    try:
        if interaction.response.is_done():
            await interaction.edit_original_response(**kwargs)
        else:
            await interaction.response.edit_message(**kwargs)
    except discord.HTTPException:
        follow: dict = {"view": view, "ephemeral": True}
        if files:
            follow["files"] = files
        try:
            if interaction.response.is_done():
                await interaction.followup.send(**follow)
            else:
                await interaction.response.send_message(**follow)
        except discord.HTTPException:
            return


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


async def _cast_failure_note(store: PlayerStore | None, pending: PendingCast) -> str:
    """Rembourse une partie de l'énergie perdue et renvoie la note à afficher."""
    refunded = 0
    if store is not None and pending.energy_cost > 0:
        try:
            refunded = await store.refund_failed_cast(
                pending.guild_id, pending.user_id, pending
            )
        except PlayerError:
            refunded = 0
    if refunded > 0:
        return f"**-{pending.energy_cost}** énergie perdue · **+{refunded}** remboursée aussitôt"
    if pending.energy_cost > 0:
        return f"**-{pending.energy_cost}** énergie perdue"
    return ""


async def run_bite_timer(
    interaction: discord.Interaction,
    catalog: Catalog,
    pending: PendingCast,
) -> None:
    store = getattr(interaction.client, "store", None)
    store = store if isinstance(store, PlayerStore) else None
    try:
        await asyncio.sleep(pending.wait_s)
        if pending.resolved:
            return
        await interaction.edit_original_response(view=BiteView(catalog, pending, phase="open"))
        await asyncio.sleep(pending.window_s)
        if pending.resolved:
            return
        pending.resolved = True
        note = await _cast_failure_note(store, pending)
        await interaction.edit_original_response(
            view=NoticeView("Fuite", "Il s'est enfui — réessaie quand la fenêtre est verte.", note=note)
        )
    except (discord.HTTPException, discord.NotFound):
        pending.resolved = True
    finally:
        if pending.resolved and store is not None:
            store.clear_active_cast(pending.guild_id, pending.user_id, pending)


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
        if pending.snap is not None:
            gear = "\n".join(_equipped_lines(catalog, pending.snap))
        else:
            keys = {
                "tool": pending.tool_key,
                "hook": pending.hook_key,
                "bait": pending.bait_key,
                "objet": pending.objet_key,
            }
            slots = DISPLAY_SLOTS if pending.method != "net" else tuple(
                s for s in DISPLAY_SLOTS if s not in ROD_ONLY_SLOTS
            )
            gear = "\n".join(_slot_item_line(catalog, slot, keys.get(slot)) for slot in slots)
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
            try:
                await _apply_view(interaction, NoticeView("Fuite", "Trop tard."))
            except discord.HTTPException:
                return
            return
        if self.phase == "waiting" and pending.trap_early:
            pending.resolved = True
            store = getattr(interaction.client, "store", None)
            store = store if isinstance(store, PlayerStore) else None
            note = await _cast_failure_note(store, pending)
            if store is not None:
                store.clear_active_cast(pending.guild_id, pending.user_id, pending)
            await _apply_view(
                interaction,
                NoticeView(
                    "Fuite",
                    "**Trop tôt** — il a senti la canne bouger avant l'heure.",
                    note=note,
                ),
            )
            return
        if self.phase != "open":
            if not interaction.response.is_done():
                try:
                    await interaction.response.defer()
                except discord.HTTPException:
                    pass
            return
        pending.resolved = True
        if not interaction.response.is_done():
            try:
                await interaction.response.defer()
            except discord.HTTPException:
                return
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
            await _maybe_auto_share_catch(interaction, catalog, result)
        except PlayerError as exc:
            await edit_error(interaction, str(exc))
            return


def _catch_share_text(catalog: Catalog, result: CastResult, display_name: str) -> str:
    species = catalog.get_species(result.species_key)
    bits = [f"**{display_name}** a pris {species.name}"]
    if result.length_cm is not None:
        bits.append(f"`{result.length_cm} cm`")
    if result.weight_kg is not None:
        bits.append(f"`{result.weight_kg} kg`")
    if result.personal_record:
        bits.append("**record perso**")
    if result.guild_rank == 1:
        bits.append("**record du serveur**")
    if result.loot_key:
        try:
            item = catalog.get_item(result.loot_key)
            if item_is_gem(item):
                bits.append(f"et {item_display(catalog, item.key)} · **exceptionnel**")
            else:
                bits.append(f"et {item.name}")
        except Exception:
            bits.append(f"et {result.loot_key}")
    return " · ".join(bits)


def _loot_is_gem(catalog: Catalog, loot_key: str | None) -> bool:
    if not loot_key:
        return False
    try:
        return item_is_gem(catalog.get_item(loot_key))
    except Exception:
        return False


async def _maybe_auto_share_catch(
    interaction: discord.Interaction, catalog: Catalog, result: CastResult
) -> None:
    gold = result.guild_rank == 1
    gem = _loot_is_gem(catalog, result.loot_key)
    if not gold and not gem:
        return
    channel = interaction.channel
    if channel is None or not hasattr(channel, "send"):
        return
    text = _catch_share_text(catalog, result, interaction.user.display_name)
    try:
        await channel.send(text)
    except discord.HTTPException:
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
        where = species_where_text(catalog, species)
        if where:
            children += [discord.ui.Separator(), discord.ui.TextDisplay(where)]
        children += [discord.ui.Separator(), discord.ui.TextDisplay(captures)]

        status = _catch_status_lines(catalog, result)
        self.result = result
        self.catalog = catalog
        shareable = bool(result.is_new or result.personal_record or result.guild_rank or result.loot_key)
        recast_ok, recast_warn = _recast_note(catalog, result)
        if recast_warn:
            status.append(recast_warn)
        if status:
            children += [discord.ui.Separator(), text_display("\n".join(status))]
        buttons = [_RecastButton(disabled=not recast_ok)]
        if shareable:
            buttons.append(_ShareCatchButton())
        append_controls(children, button_row=discord.ui.ActionRow(*buttons))
        self.add_item(make_container(*children))


def _catch_status_lines(catalog: Catalog, result: CastResult) -> list[str]:
    lines = [f"**Énergie** · `{result.energy}/{result.energy_max}`"]
    if result.bait_consumed:
        lines.append(f"**Appât** · −1 {item_display(catalog, result.bait_consumed)}")
    if result.waste_key:
        lines.append(f"**Déchet** · {item_display(catalog, result.waste_key)}")
    if result.loot_key:
        lines.append(f"**Trouvé** · {item_display(catalog, result.loot_key)}")
    if result.hook_broke:
        lines.append("**Hameçon** · usé")
    places = f"`{result.carry_used}/{result.carry_max}` places"
    if result.kept:
        lines.append(f"**Sac** · {places}")
    else:
        lines.append(f"**Relâché** · sac plein · {places}")
    if result.daily_guild_just_completed:
        lines.append("**Le village a fait la quête** · note environnementale")
    if result.daily_just_rewarded or result.daily_note:
        bits = daily_counters_text(
            catalog,
            count=result.daily_count or 0,
            target=result.daily_target,
            done=bool(result.daily_just_rewarded)
            or (
                result.daily_target > 0
                and (result.daily_count or 0) >= result.daily_target
            ),
            guild_count=result.daily_guild_count or 0,
            guild_target=result.daily_guild_target,
            guild_done=result.daily_guild_just_completed
            or (
                result.daily_guild_target > 0
                and (result.daily_guild_count or 0) >= result.daily_guild_target
            ),
        )
        if result.daily_just_rewarded:
            lines.append(
                "**Quête du jour** · "
                + format_money(result.daily_just_rewarded, catalog.game.money)
                + f" · {bits}"
            )
        else:
            lines.append(f"**Quête du jour** · {bits}")
    return lines


def _recast_note(catalog: Catalog, result: CastResult) -> tuple[bool, str]:
    snap = result.snap
    if snap is None or not _equipped_key(snap.equipped.get("tool")):
        return False, "**Équipe un outil**"
    if _tool_method(catalog, snap) != "net" and not _equipped_key(
        snap.equipped.get("hook")
    ):
        return False, "**Équipe un hameçon**"
    return _recast_energy_note(catalog, result)


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
            weather_bit = f"{weather_display(weather)} **+{extra}** énergie · "
    needed = base + extra
    if result.energy >= needed:
        return True, ""
    return False, f"**pas assez d'énergie** · {weather_bit}il faut {energy_amount(needed)}"


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
        await store.get_or_create(guild.id, interaction.user.id)
        if "milieu" in msg.lower():
            await _apply_view(
                interaction,
                await load_monde_view(
                    catalog,
                    store,
                    guild.id,
                    interaction.user.id,
                    flash="**Choisis un milieu** pour pêcher. Premier aller : **immédiat**.",
                ),
            )
            return
        if "hameçon" in msg.lower() or "crochet" in msg.lower():
            await _apply_view(
                interaction,
                await load_player_hub(
                    catalog,
                    store,
                    guild.id,
                    interaction.user.id,
                    interaction.user.display_name,
                    tab="profil",
                    flash="**Équipe un hameçon** pour pêcher.",
                ),
            )
            return
        if "outil" in msg.lower():
            await _apply_view(
                interaction,
                await load_player_hub(
                    catalog,
                    store,
                    guild.id,
                    interaction.user.id,
                    interaction.user.display_name,
                    tab="profil",
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
        text = _catch_share_text(catalog, result, interaction.user.display_name)
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


def _dex_page_lines(catalog: Catalog, rows: dict[str, DexRow], chunk) -> list[str]:
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
        where = species_context_line(catalog, spec)
        if where:
            lines.append(italic_text(where))
    return lines


class DexView(discord.ui.LayoutView):
    """Dex paginé : sprite si découvert, silhouette sinon. Pas de thumbnail PNG."""

    def __init__(
        self,
        catalog: Catalog,
        rows: dict[str, DexRow],
        *,
        display_name: str = "",
        group: str = "all",
        page: int = 0,
        found: int = 0,
        total: int = 0,
    ) -> None:
        super().__init__(timeout=180)
        self.catalog = catalog
        self.rows = rows
        self.display_name = display_name
        self.hub_tab = "dex"
        self.group = group
        self.found = found
        self.total = total
        species = _dex_species(catalog, group)
        pages = max(1, (len(species) + DEX_PAGE_SIZE - 1) // DEX_PAGE_SIZE) if species else 1
        self.page = max(0, min(page, pages - 1))
        start = self.page * DEX_PAGE_SIZE
        chunk = species[start : start + DEX_PAGE_SIZE]

        lines = _dex_page_lines(catalog, rows, chunk)

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
        prepend_tabs(children, _hub_tab_row("dex"))
        nav = None
        if pages > 1:
            nav = discord.ui.ActionRow(
                _DexNavButton(delta=-1, disabled=self.page <= 0),
                _DexNavButton(delta=1, disabled=self.page >= pages - 1),
            )
        append_controls(children, button_row=nav)
        self.add_item(make_container(*children))


class _DexNavButton(discord.ui.Button):
    def __init__(self, *, delta: int, disabled: bool) -> None:
        super().__init__(**_nav_arrow_kwargs(delta, disabled=disabled))
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, DexView):
            return
        nxt = DexView(
            parent.catalog,
            parent.rows,
            display_name=parent.display_name,
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
            display_name=parent.display_name,
            group=self.values[0],
            page=0,
            found=parent.found,
            total=parent.total,
        )
        await interaction.response.edit_message(view=nxt)


RECORDS_PAGE_SIZE = 20


class RecordsView(discord.ui.LayoutView):
    """Meilleures prises du serveur, une par espèce, paginées."""

    def __init__(
        self,
        catalog: Catalog,
        rows: list[tuple[str, int, float, float]],
        *,
        names: dict[int, str] | None = None,
        page: int = 0,
    ) -> None:
        super().__init__(timeout=120)
        self.catalog = catalog
        self.rows = rows
        self.names = names or {}
        pages = max(1, (len(rows) + RECORDS_PAGE_SIZE - 1) // RECORDS_PAGE_SIZE) if rows else 1
        self.page = max(0, min(page, pages - 1))
        start = self.page * RECORDS_PAGE_SIZE
        chunk = rows[start : start + RECORDS_PAGE_SIZE]
        lines: list[str] = []
        for species_key, user_id, length, weight in chunk:
            who = self.names.get(user_id) or f"<@{user_id}>"
            lines.append(
                "- "
                + species_display(
                    catalog,
                    species_key,
                    extra=f" · `{length} cm` · `{weight} kg` · {who}",
                )
            )
        body = "\n".join(lines) if lines else "Aucun record pour l'instant."
        subtitle = "-# Meilleure prise du serveur par espèce"
        if pages > 1:
            subtitle += f" · page {self.page + 1}/{pages}"
        children: list = [
            discord.ui.TextDisplay("## Records"),
            discord.ui.TextDisplay(subtitle),
            discord.ui.Separator(),
            discord.ui.TextDisplay(body),
        ]
        nav = None
        if pages > 1:
            nav = discord.ui.ActionRow(
                _RecordsNavButton(delta=-1, disabled=self.page <= 0),
                _RecordsNavButton(delta=1, disabled=self.page >= pages - 1),
            )
        append_controls(children, button_row=nav)
        self.add_item(make_container(*children))


class _RecordsNavButton(discord.ui.Button):
    def __init__(self, *, delta: int, disabled: bool) -> None:
        super().__init__(**_nav_arrow_kwargs(delta, disabled=disabled))
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, RecordsView):
            return
        nxt = RecordsView(
            parent.catalog,
            parent.rows,
            names=parent.names,
            page=parent.page + self.delta,
        )
        await interaction.response.edit_message(view=nxt)


LEADERBOARD_LABELS = {
    "money": "Argent",
    "dex": "Espèces découvertes",
    "archaeology": "Archéologie",
    "env_contribution": "Contribution environnementale",
}
LEADERBOARD_UNITS = {
    "money": "",
    "dex": " espèce(s)",
    "archaeology": " point(s)",
    "env_contribution": " point(s)",
}


class LeaderboardView(discord.ui.LayoutView):
    """Classement serveur : argent, dex, archéologie, contribution environnementale."""

    def __init__(
        self,
        catalog: Catalog,
        rows: list[tuple[int, int]],
        *,
        metric: str,
        names: dict[int, str] | None = None,
    ) -> None:
        super().__init__(timeout=120)
        self.catalog = catalog
        self.rows = rows
        self.metric = metric if metric in LEADERBOARD_LABELS else "money"
        self.names = names or {}
        names = self.names
        lines: list[str] = []
        medals = ["🥇", "🥈", "🥉"]
        for i, (user_id, value) in enumerate(rows):
            rank = medals[i] if i < 3 else f"`#{i + 1}`"
            who = names.get(user_id) or f"<@{user_id}>"
            if self.metric == "money":
                value_bit = format_money(value, catalog.game.money)
            else:
                value_bit = f"**{value}**{LEADERBOARD_UNITS.get(self.metric, '')}"
            lines.append(f"{rank} {who} · {value_bit}")
        body = "\n".join(lines) if lines else "Personne n'a encore de score ici."
        options = [
            discord.SelectOption(
                label=label, value=key, default=key == self.metric
            )
            for key, label in LEADERBOARD_LABELS.items()
        ]
        children: list = [
            discord.ui.TextDisplay("## Classement"),
            discord.ui.TextDisplay(f"-# {LEADERBOARD_LABELS[self.metric]} · top {len(rows) or 0}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(body),
        ]
        append_controls(
            children,
            select_row=discord.ui.ActionRow(_LeaderboardSelect(options)),
        )
        self.add_item(make_container(*children))


class _LeaderboardSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Catégorie…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, LeaderboardView):
            return
        guild = interaction.guild
        if guild is None:
            await edit_error(interaction, "Cette commande s'utilise sur un serveur.")
            return
        store = getattr(interaction.client, "store", None)
        catalog = getattr(interaction.client, "catalog", None)
        if store is None or catalog is None or not isinstance(store, PlayerStore):
            await edit_error(interaction, "AZURE n'est pas prêt.")
            return
        assert isinstance(catalog, Catalog)
        metric = self.values[0]
        rows = await store.leaderboard(guild.id, metric)
        names: dict[int, str] = {}
        for user_id, _value in rows:
            member = guild.get_member(user_id)
            names[user_id] = member.display_name if member is not None else f"<@{user_id}>"
        nxt = LeaderboardView(catalog, rows, metric=metric, names=names)
        await interaction.response.edit_message(view=nxt)


SAC_TAB_LABELS = {
    "fish": "Poissons",
    "creature": "Créatures",
    "items": "Items",
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
        display_name: str = "",
        tab: str = "fish",
        page: int = 0,
        flash: str = "",
    ) -> None:
        super().__init__(timeout=180)
        self.catalog = catalog
        self.snap = snap
        self.specimens = specimens
        self.display_name = display_name
        self.hub_tab = "sac"
        self.tab = tab if tab in SAC_TAB_LABELS else "fish"
        self.page = page

        release_row = None
        nav = None
        note = flash
        tab_row = discord.ui.ActionRow(
            *(_SacTabButton(key, active=self.tab == key) for key in SAC_TAB_LABELS)
        )

        if self.tab == "items":
            parts = _inventory_parts(catalog, snap, collectibles=None)
            pages = max(1, (len(parts) + SAC_PAGE_SIZE - 1) // SAC_PAGE_SIZE) if parts else 1
            self.page = max(0, min(page, pages - 1))
            start = self.page * SAC_PAGE_SIZE
            chunk = parts[start : start + SAC_PAGE_SIZE]
            empty = "Aucun item dans le sac."
            body = "\n".join(chunk) if chunk else empty
            subtitle = f"-# {SAC_TAB_LABELS[self.tab]}"
            if pages > 1:
                subtitle += f" · page {self.page + 1}/{pages}"
            note = flash or "Items du sac. Pour manger : onglet **Profil**."
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
            subtitle = f"-# {used}/{cap} places · {SAC_TAB_LABELS[self.tab]}"
            if pages > 1:
                subtitle += f" · page {self.page + 1}/{pages}"
            release_options: list[discord.SelectOption] = []
            for spec in chunk:
                try:
                    name = catalog.get_species(spec.species_key).name
                except Exception:
                    name = spec.species_key
                kwargs: dict = {
                    "label": select_label(name),
                    "value": str(spec.id)[:100],
                    "description": select_desc(f"{spec.length_cm} cm · {spec.weight_kg} kg"),
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
                _SacNavButton(delta=-1, disabled=self.page <= 0),
                _SacNavButton(delta=1, disabled=self.page >= pages - 1),
            )
        children: list = [
            discord.ui.TextDisplay("## Sac"),
            discord.ui.TextDisplay(subtitle),
            discord.ui.Separator(),
            discord.ui.TextDisplay(body),
        ]
        prepend_tabs(children, _hub_tab_row("sac"))
        append_controls(
            children,
            note=note,
            button_row=tab_row,
            extra_button_row=nav,
            select_row=release_row,
        )
        self.add_item(make_container(*children))


class _SacTabButton(discord.ui.Button):
    def __init__(self, tab: str, *, active: bool) -> None:
        super().__init__(
            style=discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary,
            label=SAC_TAB_LABELS[tab],
            disabled=active,
        )
        self.tab = tab

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, SacView):
            return
        nxt = SacView(
            parent.catalog,
            parent.snap,
            parent.specimens,
            display_name=parent.display_name,
            tab=self.tab,
            page=0,
        )
        await _apply_view(interaction, nxt)


class _SacNavButton(discord.ui.Button):
    def __init__(self, *, delta: int, disabled: bool) -> None:
        super().__init__(**_nav_arrow_kwargs(delta, disabled=disabled))
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, SacView):
            return
        nxt = SacView(
            parent.catalog,
            parent.snap,
            parent.specimens,
            display_name=parent.display_name,
            tab=parent.tab,
            page=parent.page + self.delta,
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
            released = await store.release_caught(
                guild.id, interaction.user.id, specimen_id
            )
        except (PlayerError, ValueError) as exc:
            await edit_error(interaction, str(exc))
            return
        snap = await store.snapshot(guild.id, interaction.user.id)
        remaining = await store.list_caught(guild.id, interaction.user.id)
        flash = f"**Relâché** · {species_display(catalog, released.species_key)}"
        nxt = SacView(
            catalog,
            snap,
            remaining,
            display_name=parent.display_name,
            tab=parent.tab,
            page=parent.page,
            flash=flash,
        )
        await _apply_view(interaction, nxt)


async def load_player_hub(
    catalog: Catalog,
    store: PlayerStore,
    guild_id: int,
    user_id: int,
    display_name: str,
    *,
    tab: str = "profil",
    sac_tab: str = "fish",
    dex_group: str = "all",
    page: int = 0,
    flash: str = "",
) -> discord.ui.LayoutView:
    """Recharge Profil / Sac / Dex pour ré-éditer le même message."""
    snap = await store.get_or_create(guild_id, user_id)
    key = tab if tab in HUB_TAB_LABELS else "profil"
    if key == "sac":
        specimens = await store.list_caught(guild_id, user_id)
        return SacView(
            catalog,
            snap,
            specimens,
            display_name=display_name,
            tab=sac_tab,
            page=page,
            flash=flash,
        )
    if key == "dex":
        rows = await store.list_dex(guild_id, user_id)
        return DexView(
            catalog,
            rows,
            display_name=display_name,
            group=dex_group,
            page=page,
            found=snap.dex_found,
            total=snap.dex_total,
        )
    return ProfilView(catalog, snap, display_name, flash=flash)


def _npc_face_emoji(npc: Npc, *, env_good: bool) -> discord.PartialEmoji | None:
    use_alt = bool((npc.portraits.good or npc.portraits.bad) and not env_good)
    return _partial_emoji(npc_emoji(npc.key, alt=use_alt))


def _npc_card_header(
    catalog: Catalog,
    npc: Npc,
    subtitle: str,
    *,
    env_good: bool,
    attachments: list,
) -> discord.ui.Item:
    """Nom + ligne d'identité à gauche du portrait, pour n'importe quel PNJ."""
    name = npc.name or npc.key
    sub = (subtitle or "").strip()
    body = discord.ui.TextDisplay(
        f"{title_name(name)}\n{sub}" if sub else title_name(name)
    )
    filename = npc_portrait_filename(npc, env_good=env_good)
    file = asset_file(catalog.assets_root / "npcs" / filename)
    if file is None:
        return body
    attachments.append(file)
    packed = section_with_thumbnail(body, media=file)
    return packed if isinstance(packed, discord.ui.Section) else body


def _repair_max(item: Item) -> int | None:
    dur = item.durability
    if dur is None:
        return None
    if dur.max_days is not None:
        return int(dur.max_days)
    if dur.max is not None:
        return int(dur.max)
    return None


async def _daily_place_block_with_contributors(
    catalog: Catalog, store: PlayerStore, guild_id: int, user_id: int
) -> str:
    status = await store.daily_status(guild_id, user_id)
    contributors = await store.daily_top_contributors(
        guild_id, status.day_key, status.milieu_key
    )
    return daily_place_block(catalog, status, contributors=contributors)


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
    talk_catch_id: int | None = None,
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
        flash = flash or "Cette personne n'est plus là."
        npc_key = None
    bargain = None
    known_keys: set[str] = set()
    if npc_key:
        bargain = await store.get_village_bargain(
            guild_id, user_id, npc_key, bucket=bucket
        )
        known_keys = await store.village_talk_known_keys(
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
        known_keys=known_keys,
        talk_catch_id=talk_catch_id,
        daily_line=await _daily_place_block_with_contributors(catalog, store, guild_id, user_id),
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
        known_keys: set[str] | None = None,
        talk_catch_id: int | None = None,
        daily_line: str = "",
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
        self.known_keys = set(known_keys or [])
        self.talk_catch_id = talk_catch_id
        self.daily_line = daily_line
        self.attachments: list[discord.File] = []
        self._confirm_used = False

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
            note = flash or "Approche-toi. **Parle-leur**, et **montre** ce que tu as."
        else:
            name = current.name or current.key
            role = npc_role_label(current)
            deal = " · **prix négociés**" if self.bargain else ""
            if role and current.description:
                ident = f"-# {purse} · **{role}** · {current.description}{deal}"
            elif role:
                ident = f"-# {purse} · **{role}**{deal}"
            else:
                ident = f"-# {purse}{deal}"
            header = _npc_card_header(
                catalog,
                current,
                ident,
                env_good=env_good,
                attachments=self.attachments,
            )
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
                        quantity=self._confirm_quantity(),
                        disabled=block is not None,
                    )
                )
                if block and not flash:
                    note = f"**{block}.**"
            button_row = discord.ui.ActionRow(*actions)
            if self.talk_status == "pending":
                note = f"**{name} réfléchit…**"
            elif self.talk_status == "streaming":
                note = f"**{name} répond…**"

        children: list = [header] if current is not None else [header, subtitle]
        if current is None:
            if self.daily_line:
                children += [
                    discord.ui.Separator(),
                    discord.ui.TextDisplay(self.daily_line),
                ]
            promo = self._promo_block()
            if promo:
                children += [discord.ui.Separator(), discord.ui.TextDisplay(promo)]
        if body:
            children += [discord.ui.Separator(), discord.ui.TextDisplay(body)]
        elif not board:
            children += [discord.ui.Separator(), discord.ui.TextDisplay("…")]
        if board:
            children += [discord.ui.Separator(), discord.ui.TextDisplay(board)]
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

    def _select_known_keys(self) -> set[str]:
        return self.known_keys | self._revealed_keys()

    def _select_price_plain(
        self, npc: Npc, key: str, *, specimen: CaughtSpecimen | None = None
    ) -> str:
        if key not in self._select_known_keys():
            return ""
        money = self.catalog.game.money
        mods = self._mods()
        if specimen is not None:
            try:
                species = self.catalog.get_species(specimen.species_key)
            except Exception:
                return ""
            price = specimen_price(
                self.catalog,
                species,
                specimen.length_cm,
                specimen.weight_kg,
                modifiers=mods,
            )
            return format_money_plain(price, money)
        try:
            item = self.catalog.get_item(key)
        except Exception:
            return ""
        role = npc.role or ""
        if role == "shop" and npc.shop_mode == "sell":
            price = apply_named_mult(int(item.economy.buy_price or 0), mods, "buy_mult")
            return format_money_plain(price, money)
        if role == "shop" and npc.shop_mode == "buy":
            if item.category == "waste":
                return format_money_plain(waste_sell_unit(item, mods), money)
            if item.economy.sell_price is None:
                return ""
            price = apply_named_mult(int(item.economy.sell_price), mods, "sell_mult")
            return format_money_plain(price, money)
        if role == "repair":
            dur = item.durability
            if dur is None or dur.repair_cost is None:
                return ""
            cost = apply_named_mult(int(dur.repair_cost), mods, "repair_mult")
            return format_money_plain(cost, money)
        if role == "special":
            unit = waste_sell_unit(item, mods)
            env = waste_env_points(item)
            bits = [format_money_plain(unit, money)]
            if env:
                bits.append(f"+{env} note")
            return " · ".join(bits)
        return ""

    def _display_board(self, npc: Npc, *, env_good: bool) -> str:
        mode = self.talk_display
        if self.talk_intent == "cleanup" and (not mode or mode == "none"):
            mode = "env" if npc.role == "special" else "purse"
        if mode == "none":
            if npc.role == "travel":
                return self._here_only()
            text = ""
        elif mode == "stock":
            text = self._board_stock(npc)
        elif mode == "purse":
            text = self._board_purse()
        elif mode == "destinations":
            text = self._board_destinations()
        elif mode == "repairs":
            text = self._board_repairs()
        elif mode == "env":
            text = self._board_env(env_good=env_good)
        elif mode == "fossils":
            text = self._board_fossils()
        elif mode == "inspect":
            text = self._board_inspect()
        else:
            text = ""
        if self.talk_intent == "cleanup":
            give = self._cleanup_give_block()
            if give:
                return f"{text}\n\n{give}" if text else give
        return text

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
            lines.append(f"- {item_display(self.catalog, it.key)} · {format_money(price, money)}{mark}")
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
            lines.append(
                "- " + species_display(catalog, spec.species_key, extra=f"{extra}{mark}")
            )
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
                    "- "
                    + self._waste_rate_line(
                        item,
                        qty=stack.quantity,
                        mark=mark,
                        modifiers=mods,
                    )
                )
                continue
            price = apply_named_mult(int(item.economy.sell_price), mods, "sell_mult")
            extra = f" ×{stack.quantity} · {format_money(price, money)}"
            lines.append("- " + item_display(catalog, item.key, extra=f"{extra}{mark}"))
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
            f"**gratuite** · carte · /monde"
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
                dests.append(f"- **{milieu.name}** · {fare} · raccourci{mark}")
            else:
                price = apply_named_mult(
                    passeur_price(self.catalog, remaining_s=None, snap=self.snap),
                    mods,
                    "travel_mult",
                )
                dests.append(
                    f"- **{milieu.name}** · {format_money(price, money)}{mark}"
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
                "- "
                + item_display(self.catalog, item.key, extra=f"{extra} · {format_money(cost, money)}{mark}")
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
        if extra:
            extra = f" · {extra}"
        return item_display(self.catalog, item.key, extra=f"{extra}{mark}")

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
        if self.talk_intent != "cleanup":
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

    def _cleanup_give_block(self) -> str:
        taken = cleanup_take(
            self.catalog,
            self.snap,
            item_key=self.talk_item_key,
            quantity=self.talk_quantity if self.talk_item_key else None,
        )
        if not taken:
            return ""
        mods = self._mods()
        money = self.catalog.game.money
        lines = ["**Tu donnes**"]
        for item, qty in taken:
            unit = waste_sell_unit(item, mods)
            env = waste_env_points(item) * qty
            bits: list[str] = []
            if qty > 1:
                bits.append(f"×{qty}")
            bits.append(format_money(unit * qty, money))
            if env:
                bits.append(f"**+{env}** note environnementale")
            extra = " · ".join(bits)
            lines.append(
                "- "
                + item_display(
                    self.catalog, item.key, extra=f" · {extra}" if extra else ""
                )
            )
        return "\n".join(lines)

    def _confirm_quantity(self) -> int:
        if self.talk_intent != "cleanup":
            return self.talk_quantity
        taken = cleanup_take(
            self.catalog,
            self.snap,
            item_key=self.talk_item_key,
            quantity=self.talk_quantity if self.talk_item_key else None,
        )
        return max(1, sum(qty for _, qty in taken))

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
            + (
                f"\n**Archéologie** · **{self.snap.archaeology_points}**"
                if self.snap.archaeology_points
                else ""
            )
        )

    def _board_inspect(self) -> str:
        revealed: list[str] = []
        for key in list(self.talk_board_keys) + list(self._revealed_keys()):
            if key and key not in revealed:
                revealed.append(key)
        if not revealed:
            return ""
        catch = next(
            (s for s in self.specimens if s.id == self.talk_catch_id),
            None,
        )
        parts: list[str] = []
        catalog = self.catalog
        for key in revealed[:4]:
            try:
                item = catalog.get_item(key)
            except Exception:
                item = None
            if item is not None:
                remaining = None
                for gear in self.snap.gear:
                    if gear.item_key == key:
                        remaining = gear.durability
                        break
                parts.append(
                    inspect_item_text(catalog, item, remaining=remaining, markdown=True)
                )
                continue
            try:
                species = catalog.get_species(key)
            except Exception:
                continue
            spec = catch if catch is not None and catch.species_key == key else None
            if spec is None:
                matches = [s for s in self.specimens if s.species_key == key]
                spec = matches[0] if len(matches) == 1 else None
            parts.append(
                inspect_species_text(catalog, species, specimen=spec, markdown=True)
            )
        if not parts:
            return ""
        return "**Dossier**\n" + "\n\n".join(parts)


class _VillageNpcSelect(discord.ui.Select):
    def __init__(
        self, present: list[Npc], current: Npc | None, *, env_good: bool
    ) -> None:
        options: list[discord.SelectOption] = []
        for npc in present:
            kwargs: dict = {
                "label": select_label(npc.name or npc.key),
                "value": npc.key[:100],
                "description": select_desc(npc_role_label(npc)),
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
            options=options[:SELECT_MAX],
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
        super().__init__(**_left_action_kwargs("Place du village"))

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
        return "Montrer un article", "Ce que tu veux lui acheter"
    if npc.role == "shop" and npc.shop_mode == "buy":
        return "Montrer quelque chose", "Ce que tu veux lui vendre"
    if npc.role == "repair":
        return "Montrer le matériel", "Ce que tu veux faire réparer"
    if npc.role == "special":
        return "Montrer un déchet", "Pour la note environnementale"
    if npc.role == "summon":
        return "Montrer un fossile", "Ce que tu veux échanger"
    if npc.role == "lore":
        return "Montrer quelque chose", "Objet ou prise à identifier"
    return "Montrer quelque chose", "En lien avec cette personne"


def _talk_show_options(parent: VillageView, npc: Npc) -> list[discord.SelectOption]:
    catalog = parent.catalog
    snap = parent.snap
    specimens = parent.specimens
    options: list[discord.SelectOption] = []
    per_catch = (npc.role == "shop" and npc.shop_mode == "buy") or npc.role == "lore"
    if per_catch:
        for spec in specimens:
            try:
                species = catalog.get_species(spec.species_key)
            except Exception:
                continue
            if npc.role != "lore" and not species.economy.sellable:
                continue
            extra = talk_select_description(
                length_cm=spec.length_cm,
                weight_kg=spec.weight_kg,
                price_plain=parent._select_price_plain(
                    npc, spec.species_key, specimen=spec
                ),
            )
            emoji = _partial_emoji(species_emoji(spec.species_key))
            kwargs = {"label": select_label(species.name), "value": f"catch:{spec.id}"[:100]}
            if extra:
                kwargs["description"] = select_desc(extra)
            if emoji is not None:
                kwargs["emoji"] = emoji
            options.append(discord.SelectOption(**kwargs))
            if len(options) >= SELECT_MAX:
                return options
    for key in talk_show_keys(catalog, npc, snap=snap, specimens=specimens):
        if per_catch:
            try:
                catalog.get_species(key)
                continue
            except Exception:
                pass
        extra = ""
        try:
            item = catalog.get_item(key)
            label = item.name
            qty = next((s.quantity for s in snap.stacks if s.item_key == key), 0)
            extra = talk_select_description(
                qty=qty,
                price_plain=parent._select_price_plain(npc, key),
            )
            emoji = _select_emoji(item.key)
        except Exception:
            try:
                species = catalog.get_species(key)
            except Exception:
                continue
            label = species.name
            have = [s for s in specimens if s.species_key == key]
            first = have[0] if have else None
            extra = talk_select_description(
                length_cm=first.length_cm if first else None,
                weight_kg=first.weight_kg if first else None,
                qty=len(have),
                price_plain=parent._select_price_plain(
                    npc, key, specimen=first
                ),
            )
            emoji = _partial_emoji(species_emoji(key))
        kwargs = {"label": select_label(label), "value": key[:100]}
        if extra:
            kwargs["description"] = select_desc(extra)
        if emoji is not None:
            kwargs["emoji"] = emoji
        options.append(discord.SelectOption(**kwargs))
        if len(options) >= SELECT_MAX:
            break
    return options[:SELECT_MAX]


class VillageTalkModal(discord.ui.Modal, title="Parler"):
    def __init__(self, parent: VillageView, npc: Npc) -> None:
        super().__init__()
        self.npc_key = npc.key
        self._specimens = parent.specimens
        name = npc.name or npc.key
        self.show: discord.ui.Select | None = None
        options = _talk_show_options(parent, npc)
        if options:
            title, hint = _talk_show_label(npc)
            self.show = discord.ui.Select(
                placeholder="Ne rien montrer — juste parler",
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
        shown_extra = None
        shown_catch_id = None
        if self.show is not None and self.show.values:
            shown = self.show.values[0]
            if shown.startswith("catch:"):
                try:
                    catch_id = int(shown.split(":", 1)[1])
                except ValueError:
                    shown = None
                else:
                    spec = next((s for s in self._specimens if s.id == catch_id), None)
                    if spec is None:
                        shown = None
                    else:
                        shown = spec.species_key
                        shown_catch_id = spec.id
                        shown_extra = (
                            f"`{spec.length_cm:g} cm` · `{spec.weight_kg:g} kg`"
                        )
        await handler(
            interaction,
            npc_key=self.npc_key,
            question=self.line.value.strip(),
            shown_key=shown,
            shown_extra=shown_extra,
            shown_catch_id=shown_catch_id,
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
            label=button_label(label),
            disabled=disabled,
        )
        self.intent = intent

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self.view
        if not isinstance(parent, VillageView) or not parent.npc_key:
            return
        if parent._confirm_used:
            if not interaction.response.is_done():
                try:
                    await interaction.response.defer()
                except discord.HTTPException:
                    pass
            return
        parent._confirm_used = True
        loaded = await _village_store(interaction)
        if loaded is None:
            parent._confirm_used = False
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
                catch_id=parent.talk_catch_id,
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
            parent._confirm_used = False
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
    catch_id: int | None = None,
) -> str:
    if intent == "travel":
        if not milieu_key:
            raise PlayerError("dis-lui d'abord où tu veux aller")
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
            raise PlayerError("dis-lui d'abord ce que tu veux lui acheter")
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
            raise PlayerError("dis-lui d'abord ce que tu veux lui vendre")
        try:
            species = catalog.get_species(item_key)
        except Exception:
            species = None
        if species is not None:
            if not species.economy.sellable:
                raise PlayerError("cette prise ne s'achète pas ici")
            qty = max(1, int(quantity))
            specimens = await store.list_caught(guild_id, user_id)
            matches = [s for s in specimens if s.species_key == item_key]
            if catch_id is not None:
                preferred = [s for s in matches if s.id == catch_id]
                rest = [s for s in matches if s.id != catch_id]
                matches = preferred + rest
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
        taken = cleanup_take(
            catalog,
            snap,
            item_key=item_key,
            quantity=quantity if item_key else None,
        )
        if not taken:
            raise PlayerError("tu n'as pas de déchet à lui donner")
        sold = 0
        env_total = 0
        money_total = 0
        bits: list[str] = []
        for item, qty in taken:
            price, _money, env = await store.sell_item(
                guild_id, user_id, item.key, quantity=qty
            )
            sold += qty
            env_total += env
            money_total += price
            extra = f" ×{qty}" if qty > 1 else ""
            bits.append(item_display(catalog, item.key, extra=extra))
        extra = f" · +{env_total} note environnementale" if env_total else ""
        return (
            f"**Nettoyé** · {' · '.join(bits)} · "
            f"{format_money_plain(money_total, catalog.game.money)}{extra}"
        )
    if intent == "repair":
        if not item_key:
            raise PlayerError("dis-lui d'abord ce que tu veux faire réparer")
        snap = await store.snapshot(guild_id, user_id)
        gear = next((g for g in snap.gear if g.item_key == item_key), None)
        if gear is None:
            raise PlayerError("tu n'as pas cet équipement sur toi")
        cost, _money = await store.repair_gear(guild_id, user_id, gear.id)
        return f"**Réparé** · {item_display(catalog, item_key)} · {format_money_plain(cost, catalog.game.money)}"
    if intent == "exchange":
        before = (await store.snapshot(guild_id, user_id)).archaeology_points
        replica, bonus_key = await store.exchange_fossil(guild_id, user_id)
        after = await store.snapshot(guild_id, user_id)
        extra = ""
        if after.archaeology_points > before:
            extra = " · **set assemblé** · **+1** archéologie"
        if bonus_key:
            extra += f" · **palier atteint** → {item_display(catalog, bonus_key)} offerte !"
        return f"**Échangé** · {item_display(catalog, replica)}{extra}"
    raise PlayerError("rien à confirmer pour l'instant")


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
        role = npc_role_label(npc)
        ident = "-# **Annonce du village**"
        if role:
            ident += f" · **{role}**"
        header = _npc_card_header(
            catalog,
            npc,
            ident,
            env_good=env_good,
            attachments=self.attachments,
        )
        children: list = [
            header,
            discord.ui.Separator(),
            discord.ui.TextDisplay(text),
        ]
        append_controls(children, note=note)
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
                _GalleryNavButton(delta=-1, disabled=index <= 0),
                _GalleryNavButton(delta=1, disabled=index >= total_pages - 1),
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
    def __init__(self, *, delta: int, disabled: bool) -> None:
        super().__init__(**_nav_arrow_kwargs(delta, disabled=disabled))
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
