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
            "AZURE se joue sur ce serveur : tu pêches, tu rentres au village, "
            "et tu recommences. L'**océan**, la **rivière** et l'**étang** "
            "sont tes trois milieux, chacun avec sa météo, ses poissons et "
            "ses créatures.\n\n"
            "Tu arrives déjà équipé d'une **canne côtière**, d'un **filet**, "
            "d'un **petit crochet** et d'un **gros crochet**. L'argent "
            "viendra plus tard, quand tu vendras tes prises. Les vues qui "
            "suivent reprennent les commandes dans l'ordre où tu t'en serviras."
        ),
    ),
    OnboardingSlide(
        title="/monde",
        body=(
            "**/monde** ouvre la carte : tu y vois où tu es, la **météo** de "
            "chaque eau, ce que coûte un lancer sur place, et tu choisis ta "
            "destination.\n\n"
            "Le premier trajet est **gratuit et immédiat**. Ensuite tu "
            "**marches**, toujours gratuitement, pendant environ **trente "
            "minutes** ; si tu veux arriver tout de suite, un **passeur** au "
            "**/village** t'y emmène contre quelques pièces. La **nuit** "
            "rend les prises plus rares, et sous la **pluie**, la **tempête** "
            "ou le **vent** chaque lancer **prend davantage d'énergie** — "
            "la carte l'affiche avant que tu partes."
        ),
    ),
    OnboardingSlide(
        title="/pecher",
        body=(
            "Une fois sur place, **/pecher** lance dans le milieu où tu te "
            "trouves. Il te faut un **outil** et un **crochet** équipés "
            "(canne ou filet, petit ou gros crochet selon ce que tu vises) ; "
            "un **appât** aide sans être obligatoire, et tout ça s'équipe "
            "dans **/profil**.\n\n"
            "Chaque lancer **consomme de l'énergie**, davantage par mauvais "
            "temps. Elle **revient toute seule**, et tu peux **manger** pour "
            "aller plus vite. Après le lancer tu **attends le bon moment** "
            "puis tu **ferres** : trop tôt ou trop tard, le poisson part. "
            "Si le sac est plein la prise est **relâchée** ; parfois tu "
            "ramènes un **déchet**, un objet, très rarement une **gemme**."
        ),
    ),
    OnboardingSlide(
        title="/profil",
        body=(
            "**/profil** rassemble trois onglets : **Profil**, **Sac** et "
            "**Dex**. Sur Profil tu **équipes** l'outil, le crochet et "
            "l'appât, et tu **manges** (pain, café…) pour récupérer de "
            "l'énergie.\n\n"
            "Le Sac tient **cinq poissons** et **cinq** autres prises "
            "(créatures, coquillages) ; au-delà, ce que tu ferreras sera "
            "relâché. Tu peux **relâcher** toi-même depuis cet onglet pour "
            "faire de la place avant d'aller vendre. Le Dex retient chaque "
            "espèce que tu as vue, avec tes meilleurs spécimens, tandis que "
            "les records du serveur se consultent avec **/records**."
        ),
    ),
    OnboardingSlide(
        title="/village",
        body=(
            "**/village** ouvre la **Place**, où les gens **changent** selon "
            "l'heure. Tu leur **parles** et tu peux **montrer** une prise ou "
            "un objet : c'est eux qui proposent de vendre, d'acheter ou de "
            "réparer, et tu confirmes ensuite.\n\n"
            "**Dan** et **Joel** vendent du matériel et de quoi manger, "
            "**Agathe** achète tes prises et tes déchets, **Maurice** et "
            "**Patrick** réparent le matériel usé, **Gabriel** et **Inti** "
            "sont les **passeurs** (trajet payant, arrivée immédiate). "
            "**Gaia** parle de l'eau, **Esmer** identifie ce que tu montres, "
            "et **Oz** n'apparaît que si tu as assez de **crânes**.\n\n"
            "Chaque jour, la Place affiche aussi la **quête du jour** : "
            "**trois prises gardées** dans **le même milieu**, le même pour "
            "tout le serveur, récompensées **une fois** par un peu de bronze."
        ),
    ),
    OnboardingSlide(
        title="C'est parti",
        body=(
            "Tu choisiras l'eau avec **/monde**, tu pêcheras avec **/pecher**, "
            "tu géreras l'équipement, la nourriture et le sac dans **/profil**, "
            "tu vendras, répareras et parleras au **/village**, et tu pourras "
            "voir les meilleures prises du serveur avec **/records**.\n\n"
            "Les **gemmes** restent dans le sac et donnent chacune **+2 % "
            "Fortune**, ce qui rend les prises rares un peu moins rares. "
            "Les **fossiles** s'assemblent tout seuls, et **Oz** peut les "
            "étudier quand il est là. Si tu as une question sur une espèce "
            "ou un objet, montre-le à **Esmer**.\n\n"
            "Choisis d'abord un milieu sur la carte : le premier aller est "
            "**immédiat**, et ensuite tu pourras **/pecher**."
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
