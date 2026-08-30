"""Helpers LayoutView / Components v2 partagés (pattern ALIBI)."""

from __future__ import annotations

from typing import Optional

import discord

from common.display import error_message


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
    select_row: Optional[discord.ui.ActionRow] = None,
) -> None:
    """Pied de vue : note optionnelle, puis boutons, puis select."""
    text = (note or "").strip()
    if text:
        if not text.startswith("-#"):
            text = f"-# {text}"
        children += [discord.ui.Separator(), discord.ui.TextDisplay(text)]
    if button_row is not None or select_row is not None:
        children.append(discord.ui.Separator())
        if button_row is not None:
            children.append(button_row)
        if select_row is not None:
            if button_row is not None:
                children.append(discord.ui.Separator())
            children.append(select_row)


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
    return discord.ui.Container(*children, **kwargs)


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
