"""Limites Discord (TextDisplay, labels)."""

import io

import discord

from common.discord_ui import (
    SELECT_LABEL_MAX,
    TEXT_DISPLAY_MAX,
    button_label,
    clamp_text,
    section_with_thumbnail,
    select_desc,
    select_label,
)


def test_clamp_text_keeps_short() -> None:
    assert clamp_text("ok") == "ok"
    assert clamp_text("") == ""


def test_clamp_text_ellipsis() -> None:
    raw = "a" * (TEXT_DISPLAY_MAX + 50)
    out = clamp_text(raw)
    assert len(out) == TEXT_DISPLAY_MAX
    assert out.endswith("…")
    assert out[:-1] == "a" * (TEXT_DISPLAY_MAX - 1)


def test_select_and_button_limits() -> None:
    long_name = "Poisson" * 40
    assert len(select_label(long_name)) <= SELECT_LABEL_MAX
    assert select_label(long_name).endswith("…")
    assert len(select_desc("x" * 200)) == 100
    assert len(button_label("Confirmer l'achat · ×999")) <= 80


def test_section_with_thumbnail_keeps_subtitle_beside_image() -> None:
    media = discord.File(io.BytesIO(b"png"), filename="portrait.png")
    title = discord.ui.TextDisplay("## Esmer")
    sub = discord.ui.TextDisplay("-# Identification")
    section = section_with_thumbnail(title, sub, media=media)
    assert isinstance(section, discord.ui.Section)
    assert len(section.children) == 2
    packed = section_with_thumbnail(title, media)
    assert isinstance(packed, discord.ui.Section)
    assert len(packed.children) == 1
