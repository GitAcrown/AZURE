"""Présentation publique AZURE — un seul texte, pas un tutoriel."""

from __future__ import annotations

from common.catalog import Catalog


def pitch_title() -> str:
    return "## AZURE"


def pitch_tagline() -> str:
    return "-# Un jeu de pêche, sur ce serveur"


def pitch_blocks(catalog: Catalog) -> list[str]:
    milieus = " · ".join(f"**{m.name}**" for m in catalog.milieus) or "trois eaux"
    n = sum(1 for s in catalog.species if s.collection.collectible)
    return [
        (
            f"Tu pêches, tu rentres au village, tu recommences. {milieus} : "
            f"**{n} espèces**, une météo qui change, et des gens qui ne sont "
            f"pas toujours les mêmes."
        ),
        (
            "**La boucle** · **/monde** · **/pecher** · **/village**\n"
            "Tu choisis une eau, tu lances, tu **ferres** au bon moment. "
            "L'énergie revient. Au village tu **parles** et tu **montres** "
            "une prise : c'est eux qui proposent de vendre, d'acheter ou de "
            "réparer."
        ),
        (
            "**Ce qui continue sans toi**\n"
            "Le **jour** et la **nuit** ne pêchent pas pareil. La **Place** "
            "tourne avec l'heure. Une **quête du jour** pour tout le serveur. "
            "Le **Dex** retient ce que tu as vu ; **/records** montre les plus "
            "belles prises."
        ),
        (
            "L'outil et l'hameçon s'équipent dans **/profil**. "
            "Le premier trajet est **immédiat** — tape **/monde** pour y aller."
        ),
    ]


def pitch_text(catalog: Catalog) -> str:
    return "\n".join([pitch_title(), pitch_tagline(), *pitch_blocks(catalog)])
