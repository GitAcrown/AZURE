"""Diaporama d'onboarding : boucles de jeu, dans l'ordre."""

from __future__ import annotations

from pathlib import Path

from common.catalog import load_catalog
from common.onboarding import SLIDES, slide_at, slide_count

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def test_onboarding_has_six_slides() -> None:
    assert slide_count() == 6
    assert slide_count() == len(SLIDES)


def test_onboarding_covers_gameplay_loops() -> None:
    titles = [s.title for s in SLIDES]
    assert titles == [
        "Bienvenue",
        "/monde",
        "/pecher",
        "/profil",
        "/village",
        "C'est parti",
    ]
    blob = "\n".join(s.body for s in SLIDES)
    assert "/monde" in blob
    assert "/pecher" in blob
    assert "/village" in blob
    assert "/profil" in blob
    assert "/records" in blob
    assert "immédiat" in blob
    assert "marches" in blob
    assert "hameçon" in blob
    assert "énergie" in blob
    assert "Agathe" in blob
    assert "Esmer" in blob
    assert "Fortune" in blob
    assert "fossiles" in blob
    assert "Place" in blob
    assert "quête du jour" in blob
    for slide in SLIDES:
        assert len(slide.body) > 180


def test_slide_at_clamps() -> None:
    assert slide_at(-1).title == SLIDES[0].title
    assert slide_at(99).title == SLIDES[-1].title
    assert slide_at(2).title == "/pecher"


def test_onboarding_view_builds_every_page() -> None:
    from cogs.azure.views import OnboardingView

    catalog = load_catalog(ASSETS)
    last = slide_count() - 1
    for i in range(slide_count()):
        view = OnboardingView(catalog, page=i)
        assert view.page == i
        labels = []
        for item in view.walk_children():
            label = getattr(item, "label", None)
            if label:
                labels.append(label)
        if i == last:
            assert "C'est parti" in labels
        else:
            assert "C'est parti" not in labels
