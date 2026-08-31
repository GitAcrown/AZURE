"""Limites Discord (TextDisplay, labels)."""

from common.discord_ui import (
    SELECT_LABEL_MAX,
    TEXT_DISPLAY_MAX,
    button_label,
    clamp_text,
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
