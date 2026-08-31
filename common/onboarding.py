"""Diaporama d'onboarding (textes seuls, sans Discord)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OnboardingSlide:
    title: str
    body: str


SLIDES: tuple[OnboardingSlide, ...] = (
    OnboardingSlide(
        title="Bienvenue",
        body=(
            "AZURE, c'est **pêcher** sur ce serveur.\n\n"
            "Trois eaux : **océan**, **rivière**, **étang**.\n"
            "Tu as déjà une **canne**, un **filet** et des **crochets**."
        ),
    ),
    OnboardingSlide(
        title="Y aller",
        body=(
            "**/monde** : la carte. Météo, coût d'un lancer, et **y aller**.\n\n"
            "Le **premier** aller est **immédiat**.\n"
            "Ensuite : **marche** gratuite, ou **passeur** au village "
            "(payant, immédiat)."
        ),
    ),
    OnboardingSlide(
        title="Lancer",
        body=(
            "**/pecher** une fois sur place.\n\n"
            "Il faut un **outil** et un **crochet** — tu les changes dans **/profil**.\n"
            "Chaque lancer **coûte de l'énergie**. Pluie, tempête, vent : **plus cher**.\n"
            "**Manger** recharge — aussi dans **/profil**."
        ),
    ),
    OnboardingSlide(
        title="Le sac",
        body=(
            "**5 poissons** et **5** autres prises, pas plus. Relâche depuis l'onglet **Sac**.\n\n"
            "Vendre : **Agathe**, au village.\n"
            "Le **dex** (**/profil**) note ce que tu as déjà vu."
        ),
    ),
    OnboardingSlide(
        title="Le village",
        body=(
            "**/village** : **parler** et **montrer**.\n\n"
            "**Dan** et **Joel** vendent · **Agathe** achète · **Maurice** répare\n"
            "Les **passeurs** t'emmènent tout de suite · **Gaia** parle de l'eau\n"
            "**Esmer** identifie ce que tu montres · **Oz** si tu as assez de crânes"
        ),
    ),
    OnboardingSlide(
        title="C'est parti",
        body=(
            "Les **gemmes** du sac : **+2 % Fortune** chacune (prises rares).\n"
            "Les **fossiles** s'assemblent ; **Oz** les étudie.\n\n"
            "Équipe, mange, dex : **/profil**. Une question : **Esmer**.\n\n"
            "Choisis une eau sur la carte. Ensuite : **/pecher**.\n"
            "Chaque jour, un avis sur la **Place** du village."
        ),
    ),
)


def slide_count() -> int:
    return len(SLIDES)


def slide_at(index: int) -> OnboardingSlide:
    if not SLIDES:
        raise IndexError("aucun slide d'onboarding")
    clamped = max(0, min(int(index), len(SLIDES) - 1))
    return SLIDES[clamped]
