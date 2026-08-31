"""Helpers LayoutView / Components v2 partagés (pattern ALIBI)."""

from __future__ import annotations

from typing import Optional

import discord

from common.display import error_message

TEXT_DISPLAY_MAX = 4000
SELECT_MAX = 25
SELECT_LABEL_MAX = 100
SELECT_DESC_MAX = 100
BUTTON_LABEL_MAX = 80


def clamp_text(text: str, limit: int = TEXT_DISPLAY_MAX) -> str:
    """Borne un texte Discord (TextDisplay 4000, labels 100, etc.)."""


def clamp_text(text: str, limit: int = TEXT_DISPLAY_MAX) -> str:
    """Borne un TextDisplay Discord (4000)."""
    raw = text or ""
    if len(raw) <= limit:
        return raw
    if limit <= 1:
        return "…"[:limit]
    return raw[: limit - 1] + "…"


def text_display(content: str) -> discord.ui.TextDisplay:
    return discord.ui.TextDisplay(clamp_text(content))


def select_label(text: str) -> str:
    return clamp_text(text or "—", SELECT_LABEL_MAX)


def select_desc(text: str) -> str:
    return clamp_text(text or "", SELECT_DESC_MAX)


def button_label(text: str) -> str:
    return clamp_text(text or "…", BUTTON_LABEL_MAX)


async def ack(interaction: discord.Interaction, *, ephemeral: bool = True) -> bool:
    """Defer sans planter si l'interaction est déjà ack ou expirée."""
    if interaction.response.is_done():
        return True
    try:
        await interaction.response.defer(ephemeral=ephemeral)
        return True
    except discord.NotFound:
        return False
    except discord.HTTPException as exc:
        if getattr(exc, "code", None) in {40060, 10062}:
            return interaction.response.is_done()
        raise


def prepend_tabs(children: list, tab_row: discord.ui.ActionRow) -> None:
    """Select d'onglets en tête de container (pattern MARIA_R)."""
    children[:0] = [tab_row, discord.ui.Separator()]


def append_controls(
    children: list,
    *,
    note: str = "",
    button_row: Optional[discord.ui.ActionRow] = None,
    extra_button_row: Optional[discord.ui.ActionRow] = None,
    select_row: Optional[discord.ui.ActionRow] = None,
    extra_select_row: Optional[discord.ui.ActionRow] = None,
) -> None:
    """Pied de vue : note optionnelle, puis boutons, puis selects."""
    text = clamp_text((note or "").strip())
    if text:
        if not text.startswith("-#"):
            text = f"-# {text}"
        children += [discord.ui.Separator(), discord.ui.TextDisplay(clamp_text(text))]
    rows = [
        row
        for row in (button_row, extra_button_row, select_row, extra_select_row)
        if row is not None
    ]
    if not rows:
        return
    children.append(discord.ui.Separator())
    for index, row in enumerate(rows):
        if index:
            children.append(discord.ui.Separator())
        children.append(row)


async def send_error(interaction: discord.Interaction, message: str, *, ephemeral: bool = True) -> None:
    text = error_message(message)
    if interaction.response.is_done():
        try:
            await interaction.edit_original_response(content=text, view=None, attachments=[])
        except discord.HTTPException:
            await interaction.followup.send(text, ephemeral=ephemeral)
        return
    await interaction.response.send_message(text, ephemeral=ephemeral)


async def edit_error(interaction: discord.Interaction, message: str) -> None:
    """Remplace un LayoutView par un texte d'erreur simple."""
    text = error_message(message)
    kwargs: dict = {"content": text, "view": None, "attachments": []}
    try:
        if interaction.response.is_done():
            await interaction.edit_original_response(**kwargs)
        else:
            await interaction.response.edit_message(**kwargs)
    except discord.HTTPException:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)


def make_container(*children, spoiler: bool = False) -> discord.ui.Container:
    kwargs = {}
    if spoiler:
        kwargs["spoiler"] = True
    safe: list = []
    for child in children:
        content = getattr(child, "content", None)
        if isinstance(child, discord.ui.TextDisplay) and isinstance(content, str):
            clamped = clamp_text(content)
            if clamped != content:
                child = discord.ui.TextDisplay(clamped)
        safe.append(child)
    return discord.ui.Container(*safe, **kwargs)


def section_with_thumbnail(body: discord.ui.Item, media):
    """Section + thumbnail, ou `body` seul si le média manque/échoue.

    `media` : `discord.File`, URL, ou None.
    """
    if not media:
        return body
    try:
        return discord.ui.Section(body, accessory=discord.ui.Thumbnail(media))
    except Exception:
        return body


async def sync_slash_to_guilds(
    bot: discord.Client, guilds: list
) -> tuple[list[str], int, int]:
    """Publie les slash sur chaque serveur (instantané) et vide le global.

    Renvoie `(noms, ok, échecs)` — un serveur en erreur n'empêche pas les autres.
    """
    names: list[str] = []
    tree = getattr(bot, "tree", None)
    if tree is None:
        return names, 0, 0
    ok = 0
    failed = 0
    for guild in guilds:
        try:
            tree.copy_global_to(guild=guild)
            synced = await tree.sync(guild=guild)
            names = [c.name for c in synced]
            ok += 1
        except discord.HTTPException:
            failed += 1
    await clear_global_slash(bot)
    return names, ok, failed


async def clear_global_slash(bot: discord.Client) -> None:
    """Supprime les slash globales côté Discord (sinon doublon avec le serveur)."""
    app_id = getattr(bot, "application_id", None)
    http = getattr(bot, "http", None)
    if app_id is None or http is None:
        return
    await http.bulk_upsert_global_commands(int(app_id), [])


async def clear_guild_slash(bot: discord.Client, guild) -> None:
    """Retire les copies serveur (garde les commandes locales pour un re-sync)."""
    tree = getattr(bot, "tree", None)
    if tree is None:
        return
    tree.clear_commands(guild=guild)
    await tree.sync(guild=guild)
