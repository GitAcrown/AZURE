"""Présentation publique AZURE (pub)."""

from __future__ import annotations

from pathlib import Path

from common.catalog import load_catalog
from common.pitch import pitch_blocks, pitch_text

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def test_pitch_is_one_card_not_a_tutorial() -> None:
    catalog = load_catalog(ASSETS)
    text = pitch_text(catalog)
    assert text.startswith("## AZURE")
    assert "Un jeu de pêche" in text
    assert "/monde" in text
    assert "/pecher" in text
    assert "/village" in text
    assert "/profil" in text
    assert "/records" in text
    assert "immédiat" in text
    assert "Dex" in text
    assert "quête du jour" in text
    assert "C'est parti" not in text
    assert "1 / 6" not in text
    n = sum(1 for s in catalog.species if s.collection.collectible)
    assert str(n) in text
    for milieu in catalog.milieus:
        assert milieu.name in text
    blocks = pitch_blocks(catalog)
    assert len(blocks) == 4
    assert all(len(b) > 80 for b in blocks)


def test_pub_view_is_a_single_persistent_card() -> None:
    from cogs.azure.views import PubView

    catalog = load_catalog(ASSETS)
    view = PubView(catalog)
    assert view.timeout is None
    labels = [
        getattr(item, "label", None)
        for item in view.walk_children()
        if getattr(item, "label", None)
    ]
    assert labels == []
    texts = [
        getattr(item, "content", "")
        for item in view.walk_children()
        if getattr(item, "content", None)
    ]
    blob = "\n".join(texts)
    assert "## AZURE" in blob
    assert "/pecher" in blob
    assert len(texts) >= 4


def test_admin_group_has_pub_command() -> None:
    from cogs.azure.azure import Azure

    names = {cmd.name for cmd in Azure.admin.walk_commands()}
    assert "pub" in names
