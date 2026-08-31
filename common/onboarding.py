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
            "AZURE, c'est **pêcher** sur ce serveur : tu choisis une eau, "
            "tu lances, tu ramènes ce que tu peux, et tu rentres au village "
            "quand tu as besoin de vendre, réparer, ou simplement parler.\n\n"
            "Il y a **trois milieux** — l'**océan**, la **rivière** et l'**étang**. "
            "Chacun a sa météo, ses poissons, et ses créatures.\n\n"
            "Tu commences avec une **canne côtière**, un **filet**, un **petit "
            "crochet** et un **gros crochet**. Pas d'argent encore : ça viendra "
            "des prises que tu vendras.\n\n"
            "Les vues suivantes suivent les commandes, dans l'ordre où tu "
            "t'en serviras."
        ),
    ),
    OnboardingSlide(
        title="/monde",
        body=(
            "**/monde**, c'est la **carte**. Tu y vois où tu es, la **météo** "
            "de chaque eau, ce que coûte un lancer sur place, et tu choisis "
            "où aller.\n\n"
            "Le **premier** trajet est **gratuit et immédiat** : tu poses le "
            "pied à l'eau tout de suite. Ensuite, tu **marches** — c'est "
            "gratuit, ça prend environ **trente minutes**. Si tu veux arriver "
            "tout de suite, un **passeur** au **/village** t'y emmène contre "
            "quelques pièces.\n\n"
            "La **nuit**, les prises se font plus rares. Sous la **pluie**, "
            "la **tempête** ou le **vent**, chaque lancer **coûte davantage "
            "d'énergie**. La carte te le montre avant de partir."
        ),
    ),
    OnboardingSlide(
        title="/pecher",
        body=(
            "Une fois sur place, **/pecher** lance dans le milieu où tu es.\n\n"
            "Il te faut un **outil** et un **crochet** équipés — canne ou "
            "filet, petit ou gros crochet, selon ce que tu vises. Un **appât** "
            "aide, mais ce n'est pas obligatoire. Tout ça s'équipe dans "
            "**/profil**.\n\n"
            "Chaque lancer **consomme de l'énergie** (davantage par mauvais "
            "temps). L'énergie **revient toute seule**, et tu peux **manger** "
            "pour aller plus vite.\n\n"
            "Après le lancer, **attends le bon moment**, puis **ferre**. "
            "Trop tôt ou trop tard, ça part. Si le sac est plein, la prise "
            "est **relâchée**. Parfois tu ramènes un **déchet**, un objet, "
            "très rarement une **gemme**."
        ),
    ),
    OnboardingSlide(
        title="/profil",
        body=(
            "**/profil**, c'est toi : trois onglets, **Profil**, **Sac** et "
            "**Dex**.\n\n"
            "Sur **Profil**, tu **équipes** l'outil, le crochet et l'appât, "
            "et tu **manges** (pain, café…) pour récupérer de l'énergie.\n\n"
            "Le **Sac** tient **cinq poissons** et **cinq** autres prises "
            "(créatures, coquillages). Au-delà, ce que tu ferreras sera "
            "relâché. Tu peux **relâcher** toi-même depuis cet onglet, pour "
            "faire de la place avant d'aller vendre.\n\n"
            "Le **Dex** retient chaque espèce vue, avec tes meilleurs "
            "spécimens. Les records du **serveur**, eux, sont dans **/records**."
        ),
    ),
    OnboardingSlide(
        title="/village",
        body=(
            "**/village** ouvre la **Place**. Les gens **changent** selon "
            "l'heure : tu leur **parles**, et tu peux **montrer** une prise "
            "ou un objet. C'est eux qui décident quoi te vendre, t'acheter, "
            "ou te réparer — tu confirmes ensuite.\n\n"
            "- **Dan** et **Joel** vendent du matériel et de quoi manger\n"
            "- **Agathe** achète tes prises et tes déchets\n"
            "- **Maurice** et **Patrick** réparent le matériel usé\n"
            "- **Gabriel** et **Inti** sont les **passeurs** : trajet payant, "
            "arrivée immédiate\n"
            "- **Gaia** parle de l'eau ; **Esmer** identifie ce que tu montres\n"
            "- **Oz** n'apparaît que si tu as assez de **crânes**\n\n"
            "Sur la Place, chaque jour, la **quête du jour** : **trois prises "
            "gardées** dans **le même milieu** (le même pour tout le serveur). "
            "La récompense, **une fois** : un peu de bronze."
        ),
    ),
    OnboardingSlide(
        title="C'est parti",
        body=(
            "La boucle, c'est ça : **/monde** pour choisir l'eau, **/pecher** "
            "sur place, **/profil** pour équiper, manger et gérer le sac, "
            "**/village** pour vendre, réparer, parler — et **/records** si "
            "tu veux voir les meilleures prises du serveur.\n\n"
            "Les **gemmes** que tu trouves restent dans le sac : chacune "
            "donne **+2 % Fortune**, ce qui rend les prises rares un peu "
            "moins rares. Les **fossiles** s'assemblent tout seuls ; **Oz** "
            "peut les étudier quand il est là.\n\n"
            "Une question sur une espèce ou un objet : montre-le à **Esmer**.\n\n"
            "Choisis d'abord un milieu sur la carte. Le premier aller est "
            "**immédiat**. Ensuite, **/pecher**."
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
